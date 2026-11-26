"""Windows smoke test on an isolated real app-mode window, its server and saved SQLite shift."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
from urllib.error import URLError

from test_cases import request
from test_truck_runs import command, confirm, truck


def wait_window(folder, proc):
    deadline=time.monotonic()+45
    while time.monotonic()<deadline and proc.poll() is None:
        try:
            with (folder/"data"/"launcher.lock").open("rb",buffering=0) as f:
                f.seek(1)
                port,hwnd,pid=json.loads(f.read())
            if hwnd and ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)):
                return f"http://127.0.0.1:{port}",hwnd,pid
        except (OSError, ValueError):
            pass
        time.sleep(.15)
    raise RuntimeError(f"Atlas window did not appear (process status {proc.poll()})")


def verify(exe):
    user=ctypes.windll.user32
    with TemporaryDirectory(prefix="atlas-window-") as temp:
        folder=Path(temp)
        target=shutil.copy2(exe,folder/"Atlas-PVZ.exe")
        env=dict(os.environ, LOCALAPPDATA=str(folder/"profile"))
        for launch in range(2):
            proc=subprocess.Popen([target],cwd=folder,env=env)
            hwnd=0
            try:
                url,hwnd,pid=wait_window(folder,proc)
                if launch==0:
                    request(url,"/api/demo/reset",{"scenario":"case1"})
                    request(url,"/api/demo/step",{})
                    state=request(url,"/api/state")
                    assert state["step"]==1 and state["lots"]
                    route=[("F",["Т-01"],[]),("A",[],["Т-01"])]
                    run=truck(url,confirm(url,"sample",route))
                    run=command(url,run,"start")
                    run=command(url,run,"scan",kind="pickup",order_id="Т-01")
                    duplicate=subprocess.run([target],cwd=folder,env=env,timeout=20)
                    assert duplicate.returncode==0 and wait_window(folder,proc)==(url,hwnd,pid)
                else:
                    restored=request(url,"/api/state")
                    for key in ("epoch","step","lots","ledger"):
                        assert restored[key]==state[key],key
                    assert truck(url)==run and run["load"]["ids"]==["Т-01"]
                # WM_CLOSE is the same close request issued by the title bar's X.
                assert user.PostMessageW(wintypes.HWND(hwnd),0x0010,0,0)
                assert proc.wait(timeout=20)==0
                assert not user.IsWindow(wintypes.HWND(hwnd))
                try:
                    request(url,"/health/ready")
                except URLError:
                    pass
                else:
                    raise AssertionError("Server stayed active after closing its window")
            finally:
                if proc.poll() is None:
                    if hwnd:
                        user.PostMessageW(wintypes.HWND(hwnd),0x0010,0,0)
                    subprocess.run(["taskkill","/T","/F","/PID",str(proc.pid)],capture_output=True)
                    proc.wait(timeout=10)
        # Chromium can finish flushing its isolated profile shortly after its last window closes.
        for _ in range(50):
            try:
                shutil.rmtree(folder/"profile")
                break
            except PermissionError:
                time.sleep(.2)
            except FileNotFoundError:
                break
    print("PASS: native app window, duplicate launch, close, server exit, restart and saved shift.")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--exe",type=Path,required=True)
    verify(parser.parse_args().exe.resolve())
