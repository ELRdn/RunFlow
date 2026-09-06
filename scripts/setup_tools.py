"""Fetch pinned portable tools into .tools and verify each SHA-256 before extraction."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def main():
    p=argparse.ArgumentParser();p.add_argument("--download",action="store_true");a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    lock=json.loads((root/"configs/toolchain.lock.json").read_text(encoding="utf-8"))
    for item in lock["downloads"]:
        archive=root/".tools/downloads"/item["filename"]
        if not archive.exists():
            if not a.download:raise SystemExit("Missing archive; rerun with --download: "+archive.name)
            archive.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(["curl.exe","--fail","--location","--silent","--show-error",item["url"],"-o",str(archive)],check=True)
        with archive.open("rb") as stream:actual=hashlib.file_digest(stream,"sha256").hexdigest()
        if actual != item["sha256"]:raise SystemExit("SHA-256 mismatch: "+archive.name)
        destinations={"blender":".tools/blender","umaviewer":".tools/umaviewer/runtime","mmd_tools":".tools/mmd/addons/mmd_tools"}
        out=root/destinations[item["name"]]
        if not out.exists():
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    if not (out/name).resolve().is_relative_to(out.resolve()):raise SystemExit("Unsafe archive path")
                z.extractall(out)
        print(item["name"],item["version"],"ARCHIVE_VERIFIED")
    wheels=root/".tools/mmd/addons/mmd_tools/wheels"
    deps=root/".tools/mmd/wheeldeps"
    if not deps.exists():
        for path in wheels.glob("*.whl"):
            with zipfile.ZipFile(path) as z:z.extractall(deps)


if __name__=="__main__":main()
