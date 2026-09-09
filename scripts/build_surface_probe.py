"""Build a separate diagnostic using installed Foundation14 headers/libraries."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import os
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
if __name__=='__main__':
    assert os.environ.get('WM_PROJECT_VERSION')=='14'
    build=Path(tempfile.mkdtemp(prefix='runflow-probe-build-'))
    dest=ROOT/'.tools/openfoam-surface-probe';dest.mkdir(exist_ok=True)
    (build/'Make').mkdir();shutil.copyfile(ROOT/'integrations/openfoam/surfaceProbe.C',build/'surfaceProbe.C')
    (build/'Make/files').write_text('surfaceProbe.C\n\nEXE = '+str(build/'surfaceProbe')+'\n')
    (build/'Make/options').write_text('EXE_INC = -I$(LIB_SRC)/triSurface/lnInclude -I$(LIB_SRC)/meshTools/lnInclude\n\nEXE_LIBS = -ltriSurface -lmeshTools\n')
    r=subprocess.run(['wmake'],cwd=build,timeout=300)
    if r.returncode:raise SystemExit(r.returncode)
    shutil.copyfile(build/'surfaceProbe',dest/'surfaceProbe');(dest/'surfaceProbe').chmod(0o755)
    sources=[ROOT/'integrations/openfoam/surfaceProbe.C',
      Path('/opt/openfoam14/src/meshTools/indexedOctree/treeDataPrimitivePatch.C'),
      Path('/opt/openfoam14/src/meshTools/triSurface/triSurfaceSearch/triSurfaceSearch.C'),
      Path('/opt/openfoam14/src/OpenFOAM/meshes/primitiveShapes/triangle/triangleI.H'),
      Path('/opt/openfoam14/src/triSurface/triSurface/interfaces/OBJ/readOBJ.C')]
    (dest/'build.json').write_text(json.dumps(dict(binary_sha256=sha(dest/'surfaceProbe'),source_hashes={str(p):sha(p) for p in sources},
        package=subprocess.check_output(['dpkg-query','-W','-f=${Version}','openfoam14'],text=True)),indent=2))
    print('SURFACE_PROBE_BUILT',sha(dest/'surfaceProbe'),flush=True)
