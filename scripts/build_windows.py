"""Build the portable edition from the original unsigned x64 loader and the web assets.

The PyInstaller package is an overlay. Reuse its bootloader, bundled interpreter,
entry point and compressed Python modules byte-for-byte. Replace only project data.
"""
import hashlib
import marshal
from pathlib import Path
import struct
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import zlib

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "vendor" / "windows"
EXPECTED = "7cd714ca5f05f2de8afda327436a402ad790b224259b89bcba4f4792a6b8bf4d"
COOKIE = struct.Struct("!8sIIII64s")
RECORD = struct.Struct("!IIIIBc")
MARKER = bytes.fromhex("4d45490c0b0a0b0e")


def verify_modules(pyz):
    table = dict(marshal.loads(pyz[int.from_bytes(pyz[8:12], "big"):]))
    for file in (ROOT / "app").glob("*.pyc"):
        _, offset, length = table[file.stem]
        payload = zlib.decompress(pyz[offset:offset + length])
        if file.read_bytes() != pyz[4:8] + bytes(12) + payload:
            raise ValueError(f"{file.name} differs from the Windows backend")


def assemble(original):
    if hashlib.sha256(original).hexdigest() != EXPECTED:
        raise ValueError("Unexpected original Atlas-PVZ.exe checksum")
    magic, total, toc_offset, toc_size, version, dll = COOKIE.unpack(original[-COOKIE.size:])
    if magic != MARKER:
        raise ValueError("Unexpected PyInstaller archive")
    start = len(original) - total
    position = start + toc_offset
    end = position + toc_size
    app = ROOT / "app"
    resources = {p.relative_to(app).as_posix(): p for folder in ("static", "fixtures")
                 for p in (app / folder).rglob("*") if p.is_file()}
    resources["openapi.json"] = app / "openapi.json"
    data, toc = bytearray(), bytearray()
    while position < end:
        length, offset, size, unpacked, flag, kind = RECORD.unpack_from(original, position)
        name_field = original[position + RECORD.size:position + length]
        name = name_field.rstrip(b"\0").decode().replace("\\", "/")
        payload = original[start + offset:start + offset + size]
        if name == "PYZ.pyz":
            verify_modules(zlib.decompress(payload) if flag else payload)
        if name in resources:
            raw = resources.pop(name).read_bytes().replace(b"\r\n", b"\n")
            unpacked = len(raw)
            payload = zlib.compress(raw, 9) if flag else raw
        toc.extend(RECORD.pack(length, len(data), len(payload), unpacked, flag, kind) + name_field)
        data.extend(payload)
        position += length
    if position != end or resources:
        raise ValueError(f"Unexpected project resource layout: {sorted(resources)}")
    footer = COOKIE.pack(magic, len(data) + len(toc) + COOKIE.size, len(data), len(toc), version, dll)
    return original[:start] + data + toc + footer


def main():
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    exe = out / "Atlas-PVZ.exe"
    exe.write_bytes(assemble((ORIGINAL / exe.name).read_bytes()))
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
