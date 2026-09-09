"""Build the isolated exact geometry tools with the installed Windows compiler."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import time

REPO=Path(__file__).resolve().parents[1]
ROOT=REPO/'.tools/local-geometry-6.2.1'
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    build=ROOT/'native-build';build.mkdir(exist_ok=True)
    scratch=build/'tmp';scratch.mkdir(exist_ok=True)
    env={k.upper():v for k,v in os.environ.items()}
    env.update(TEMP=str(scratch),TMP=str(scratch))
    vs=Path('C:/Program Files/Microsoft Visual Studio/2022/Community')
    cmake=shutil.which('cmake');gmp=ROOT/'auxiliary/gmp'
    commands=[
      [cmake,'-S',str(REPO/'integrations/geometry'),'-B',str(build),'-G','Visual Studio 17 2022','-A','x64',
       '-DCMAKE_GENERATOR_INSTANCE='+str(vs),'-DCGAL_DIR='+str(ROOT/'CGAL-6.2.1'),
       '-DRUNFLOW_BOOST_ROOT='+str(ROOT/'boost_1_87_0'),
       '-DGMP_INCLUDE_DIR='+str(gmp/'include'),'-DGMP_LIBRARIES='+str(gmp/'lib/gmp.lib'),
       '-DMPFR_INCLUDE_DIR='+str(gmp/'include'),'-DMPFR_LIBRARIES='+str(gmp/'lib/mpfr.lib')],
      [cmake,'--build',str(build),'--config','Release','--parallel','2']]
    records=[]
    attempt=time.time_ns()
    for i,command in enumerate(commands):
        log=build/f'build-{attempt}-{i}.log'
        with log.open('wb') as stream:
            r=subprocess.run(command,env=env,cwd=REPO,stdout=stream,stderr=subprocess.STDOUT,timeout=1200)
        records.append(dict(command=command,returncode=r.returncode,log_sha256=sha(log)))
        print(log.read_text(encoding='utf-8',errors='replace')[-7000:],flush=True)
        if r.returncode:raise RuntimeError('Native build failed; inspect '+str(log))
    for path in (gmp/'bin').glob('*.dll'): shutil.copyfile(path,build/'Release'/path.name)
    sources={p.relative_to(REPO).as_posix():sha(p) for p in (REPO/'integrations/geometry').rglob('*') if p.is_file()}
    files={p.name:sha(p) for p in (build/'Release').iterdir() if p.suffix in ('.exe','.dll')}
    compiler=vs/'VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64'
    compiler_hashes={p.name:sha(p) for p in [compiler/n for n in ('cl.exe','c1xx.dll','c2.dll','link.exe')]}
    (ROOT/'build.json').write_text(json.dumps(dict(cgal='6.2.1',install_manifest_sha256=sha(ROOT/'install.json'),
        cmake_sha256=sha(cmake),commands=records,source_hashes=sources,files=files,compiler_hashes=compiler_hashes),indent=2),encoding='utf-8')
    print('PINNED_GEOMETRY_BUILD_READY',flush=True)

if __name__=='__main__':main()
