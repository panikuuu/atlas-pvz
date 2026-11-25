"""Build the standalone window and package the same backend and client as Docker."""
import hashlib
import importlib.util
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "vendor" / "windows"

def main():
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    exe = out / "Atlas-PVZ.exe"
    app = ROOT / "app"
    if os.name != "nt" or (app / "server.pyc").read_bytes()[:4] != importlib.util.MAGIC_NUMBER:
        raise SystemExit("Build on Windows x64 with CPython 3.15.1 and PyInstaller 6.22.3")
    with tempfile.TemporaryDirectory(prefix="atlas-build-") as work:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--noupx",
                        "--name", exe.stem, "--workpath", work, "--specpath", work, "--distpath", str(out),
                        "--paths", str(app), "--add-data", f"{app / 'openapi.json'}:.",
                        "--add-data", f"{app / 'fixtures'}:fixtures", "--add-data", f"{app / 'static'}:static",
                        str(ROOT / "scripts" / "desktop.py")], check=True)
    archive = out / "Atlas-PVZ-Windows-x64.zip"
    files = {exe.name: exe, "Как запустить.txt": ORIGINAL / "Как запустить.txt"}
    files.update({"licenses/" + p.name: p for p in (ORIGINAL / "licenses").glob("*.txt")})
    with ZipFile(archive, "w") as target:
        for name, file in sorted(files.items()):
            info = ZipInfo(name, date_time=(2026, 11, 25, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            target.writestr(info, file.read_bytes(),
                            compress_type=ZIP_DEFLATED, compresslevel=9)
    checksums = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in (exe, archive)]
    (out / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="ascii")
    print("\n".join(checksums))


if __name__ == "__main__":
    main()
