"""Windows entry point. The browser engine renders the same loopback service as Docker."""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import errno
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import winreg

import server
from fleet_api import FleetHandler, bootstrap


USER = ctypes.WinDLL("user32", use_last_error=True)
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
USER.EnumWindows.argtypes = (CALLBACK, wintypes.LPARAM)
USER.IsWindow.argtypes = USER.IsWindowVisible.argtypes = (wintypes.HWND,)
USER.GetWindowTextW.argtypes = USER.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
USER.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
USER.SetForegroundWindow.argtypes = USER.IsIconic.argtypes = (wintypes.HWND,)
USER.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)


def find_engine():
    for name, subdir in (("msedge.exe", "Microsoft/Edge"), ("chrome.exe", "Google/Chrome")):
        key = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + name
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, key) as app:
                    candidate = Path(winreg.QueryValueEx(app, "")[0].strip('"'))
                if candidate.is_file():
                    return candidate
            except OSError:
                pass
        for base in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            if os.environ.get(base):
                candidate = Path(os.environ[base]) / subdir / "Application" / name
                if candidate.is_file():
                    return candidate
    raise RuntimeError("Для окна Атласа нужен установленный Microsoft Edge или Google Chrome.")


def owner(hwnd):
    pid = wintypes.DWORD()
    USER.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def locate_window(port):
    # Chromium may delegate the launch to its existing, Atlas-only profile process.
    # The port in the initial page title identifies this instance even after that handoff.
    marker = f"Atlas-PVZ [{port}]"
    found = []
    @CALLBACK
    def match(hwnd, unused):
        title = ctypes.create_unicode_buffer(512)
        cls = ctypes.create_unicode_buffer(128)
        if USER.IsWindowVisible(hwnd):
            USER.GetClassNameW(hwnd, cls, len(cls))
            USER.GetWindowTextW(hwnd, title, len(title))
            if cls.value.startswith("Chrome_WidgetWin_") and marker in title.value:
                found.append(hwnd)
                return False
        return True
    USER.EnumWindows(match, 0)
    return found[0] if found else None


@contextmanager
def claim(data):
    # Lock protocol is compatible with previous releases (byte zero is reserved).
    with (data / "launcher.lock").open("a+b", buffering=0) as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EDEADLK):
                raise
            yield None
            return
        try:
            lock.truncate(0)
            lock.write(b" ")
            yield lock
        finally:
            lock.truncate(1)
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def publish(lock, port, hwnd=0):
    lock.truncate(1)
    lock.write(json.dumps([port, hwnd, owner(hwnd) if hwnd else 0]).encode("ascii"))


def existing(data, headless):
    for _ in range(300):
        with (data / "launcher.lock").open("rb", buffering=0) as handle:
            handle.seek(1)
            try:
                value=json.loads(handle.read())
            except ValueError:
                value=None
        if isinstance(value, list):
            port, hwnd, pid = value
            if headless:
                print(f"http://127.0.0.1:{port}/", flush=True)
                return
            if hwnd and USER.IsWindow(hwnd) and owner(hwnd)==pid:
                if USER.IsIconic(hwnd):
                    USER.ShowWindow(hwnd, 9)
                USER.SetForegroundWindow(hwnd)
                return
        time.sleep(.1)
    raise RuntimeError("В этой папке уже работает сервер. Завершите его перед открытием окна.")


class LocalServer(server.ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = False
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def listen():
    try:
        return LocalServer(("127.0.0.1", 8080), FleetHandler)
    except OSError as exc:
        if exc.winerror not in (10048, 10013):
            raise
        return LocalServer(("127.0.0.1", 0), FleetHandler)


def desktop_window(port, lock, folder):
    profile_key = hashlib.sha256(os.fsencode(os.path.normcase(folder))).hexdigest()[:20]
    profile = Path(os.environ["LOCALAPPDATA"]) / "AtlasPVZ" / "Window" / profile_key
    subprocess.Popen([str(find_engine()), f"--user-data-dir={profile}", "--no-first-run",
                      "--no-default-browser-check", "--disable-background-mode",
                      f"--app=http://127.0.0.1:{port}/?desktop=1", "--window-size=1360,900"])
    for _ in range(300):
        hwnd = locate_window(port)
        if hwnd:
            break
        time.sleep(.1)
    else:
        raise RuntimeError("Браузер не открыл окно Атласа за 30 секунд.")
    pid=owner(hwnd)
    publish(lock,port,hwnd)
    while USER.IsWindow(hwnd) and owner(hwnd)==pid:
        time.sleep(.15)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args=parser.parse_args()
    folder=Path(sys.executable).resolve().parent
    server.DATA=folder / "data"
    server.DEMO_MODE=True
    os.environ["PVZ_QUIET"]="1"
    server.DATA.mkdir(exist_ok=True)
    with claim(server.DATA) as lock:
        if lock is None:
            existing(server.DATA,args.no_browser)
            return
        with listen() as http:
            bootstrap()
            publish(lock,http.server_port)
            if args.no_browser:
                print(f"http://127.0.0.1:{http.server_port}/",flush=True)
                http.serve_forever()
                return
            worker=threading.Thread(target=http.serve_forever)
            worker.start()
            try:
                desktop_window(http.server_port,lock,folder)
            finally:
                http.shutdown()
                worker.join()


if __name__=="__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if "--no-browser" in sys.argv:
            raise
        USER.MessageBoxW(None, str(exc), "Атлас доставки", 16)
        sys.exit(1)
