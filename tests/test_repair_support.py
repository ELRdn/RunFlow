import importlib.util
import os
from pathlib import Path
import sys
import numpy as np
import pytest

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts'))
from repair_trial_support import guarded,manifold_backend
from runflow.shape_fullbody import LIMITS


@pytest.mark.skipif(os.name!='nt',reason='Windows job-memory limit')
def test_os_commit_cap_denies_large_allocation_and_stops_tree(tmp_path):
    command=[sys.executable,'-c',
        'try:\n a=bytearray(256*1024**2)\n print("UNEXPECTED_ALLOCATION")\nexcept MemoryError:\n print("HARD_CAP_DENIED")']
    result=guarded(command,root=tmp_path,log=tmp_path/'guard.log',timeout=20,
                   limits={**LIMITS,'private_commit_bytes':128*1024**2})
    assert result['returncode']==0 and result['reason'] is None
    assert result['termination_verified']
    assert 'HARD_CAP_DENIED' in (tmp_path/'guard.log').read_text()
    assert result['peak_private_commit_bytes']<=128*1024**2


def test_manifold_union_preserves_outside_patch_and_removes_internal_patch():
    if not (REPO/'.tools/manifold3d-3.5.2/install.json').exists(): pytest.skip('Optional pinned backend absent')
    m=manifold_backend(REPO)
    body=m.Manifold.cube((.01,.01,.01))
    external=m.Manifold.cube((.004,.004,.002)).translate((.003,.003,.009))
    internal=m.Manifold.cube((.001,.001,.001)).translate((.004,.004,.004))
    result=body+external+internal
    assert result.status()==m.Error.NoError
    assert result.volume()==pytest.approx(1e-6+.004*.004*.001,rel=1e-6)
    v=np.asarray(result.to_mesh64().vert_properties)
    assert v[:,2].max()==pytest.approx(.011)
    assert not np.any(np.all((v>.003)&(v<.006),axis=1))
