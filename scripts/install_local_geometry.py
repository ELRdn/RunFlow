"""Install SHA-pinned header-only CGAL and its Windows dependencies locally."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]/'.tools/local-geometry-6.2.1'
ASSETS=[
 ('https://github.com/CGAL/cgal/releases/download/v6.2.1/CGAL-6.2.1-library.zip','db49ffa9d2c5a3386e0725983bf3478e3fd2ade43553f8fc3900e18554decd49'),
 ('https://github.com/CGAL/cgal/releases/download/v6.2.1/CGAL-6.2.1-win64-auxiliary-libraries-gmp-mpfr.zip','606e242c7d3b2dcdd7a04143282b4594debbe6d182f9b094ece0f3c8c6bc7988'),
 ('https://archives.boost.io/release/1.87.0/source/boost_1_87_0.tar.bz2','af57be25cb4c4f4b413ed692fe378affb4352ea50fbe294a11ef548f4d527d89')]

def main():
    ROOT.mkdir(exist_ok=False)
    records=[]
    for url,sha in ASSETS:
        dest=ROOT/url.rsplit('/',1)[1]
        print('DOWNLOAD',dest.name,flush=True)
        with urllib.request.urlopen(url,timeout=60) as response, dest.open('xb') as output:
            shutil.copyfileobj(response,output,1024*1024)
        with dest.open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=sha: raise ValueError('Archive hash mismatch: '+dest.name)
        if dest.suffix=='.zip':
            with zipfile.ZipFile(dest) as archive:
                for member in archive.infolist():
                    if not (ROOT/member.filename).resolve().is_relative_to(ROOT.resolve()): raise ValueError('Archive traversal')
                archive.extractall(ROOT)
        else:
            with tarfile.open(dest,'r:bz2') as archive:
                for member in archive:
                    # Only the Boost headers and license are required; no executable bootstrap.
                    if not (member.name.startswith('boost_1_87_0/boost/') or member.name=='boost_1_87_0/LICENSE_1_0.txt'): continue
                    if not member.isfile() or not (ROOT/member.name).resolve().is_relative_to(ROOT.resolve()): continue
                    target=ROOT/member.name; target.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as source,target.open('xb') as out: shutil.copyfileobj(source,out)
        records.append(dict(url=url,sha256=sha,bytes=dest.stat().st_size))
        print('VERIFIED',dest.name,flush=True)
    files={}
    for path in sorted(ROOT.rglob('*')):
        if path.is_file() and path.suffix not in ('.zip','.bz2'):
            with path.open('rb') as stream: files[path.relative_to(ROOT).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
    (ROOT/'install.json').write_text(json.dumps(dict(cgal='6.2.1',commit='28811b671a12b5caa9e3688569dadbc6b3728fe6',boost='1.87.0',archives=records,files=files),indent=2),encoding='utf-8')
    print('LOCAL_GEOMETRY_HEADERS_READY',len(files),flush=True)

if __name__=='__main__': main()
