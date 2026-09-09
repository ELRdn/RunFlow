"""Install the pinned optional Windows backend into an isolated project directory."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

URL='https://files.pythonhosted.org/packages/26/69/0898143298759cd8fe767bcc1c050eead973ddbb4780bf6ec277bbee949c/manifold3d-3.5.2-cp312-cp312-win_amd64.whl'
SHA256='a129d7a09421dd5e246503006c0f39f7dc73933b4ba80f4eae5e267805aac72f'


def main():
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12): raise ValueError('CPython 3.12 on Windows required')
    target=Path(__file__).resolve().parents[1]/'.tools/manifold3d-3.5.2'
    target.mkdir(exist_ok=False)
    with urllib.request.urlopen(URL,timeout=45) as response: data=response.read()
    if hashlib.sha256(data).hexdigest()!=SHA256: raise ValueError('Published wheel SHA mismatch')
    wheel=target/URL.rsplit('/',1)[1]; wheel.write_bytes(data)
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            if not (target/member.filename).resolve().is_relative_to(target.resolve()): raise ValueError('Unsafe archive path')
        archive.extractall(target)
    manifest=dict(version='3.5.2',url=URL,wheel_sha256=SHA256,
        files={p.relative_to(target).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in target.rglob('*') if p.is_file()},
        isolation='Process-specific sys.path; no existing environment or lockfile changed')
    (target/'install.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('PINNED_MANIFOLD_WHEEL_READY',target)


if __name__=='__main__': main()
