import numpy as np
import pytest
from runflow.shape_audit import SAMPLE_DTYPE,summarize_samples,source_components,cache_surface,file_sha,load_surface


def test_weighted_distance_bounds_cover_small_and_large_faces():
    samples=np.array([((0,0,0),.001,.0001,9.,0),((1,0,0),.01,.001,1.,1)],dtype=SAMPLE_DTYPE)
    result=summarize_samples(samples)
    assert result['area_weighted_mean_m']==pytest.approx(.0019)
    assert result['area_weighted_quantiles_m']['0.5']==pytest.approx(.001)
    threshold=result['thresholds']['0.002']
    assert threshold['definitely_over_fraction']==pytest.approx(.1)
    assert threshold['possibly_over_fraction']==pytest.approx(.1)
    assert result['global_max_lower_m']<.01<result['global_max_upper_m']


def test_components_merge_exact_uv_seams_but_not_separate_geometry():
    v=np.array([(0,0,0),(1,0,0),(0,1,0),(0,0,0),(0,0,1),(4,0,0),(5,0,0),(4,1,0)])
    f=np.array([(0,1,2),(3,1,4),(5,6,7)])
    labels=source_components(v,f)
    assert labels[0]==labels[1] and labels[0]!=labels[2]


def test_surface_cache_hash_indices_and_no_mutation(tmp_path):
    source=tmp_path/'source.obj'; source.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n')
    sha=file_sha(source)
    with pytest.raises(ValueError,match='hash'): cache_surface(source,tmp_path/'bad','0'*64)
    result=cache_surface(source,tmp_path/'cache',sha)
    assert result['triangles']==1 and file_sha(source)==sha
    with pytest.raises(ValueError,match='Fresh'): cache_surface(source,tmp_path/'cache',sha)
    load_surface(tmp_path/'cache')
    np.save(tmp_path/'cache/vertices.npy',np.zeros((3,3)))
    with pytest.raises(ValueError,match='cache hash'): load_surface(tmp_path/'cache')


def test_pinned_blender_complete_distance_cover(tmp_path):
    from pathlib import Path
    import subprocess
    root=Path(__file__).resolve().parents[1]
    blender=root/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
    if not blender.exists(): pytest.skip('Pinned Blender unavailable')
    result=subprocess.run([str(blender),'--background','--factory-startup','--threads','4',
        '--python-exit-code','2','--python',str(root/'tests/blender_shape_audit.py'),'--',str(tmp_path/'cover')],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'BLENDER_SHAPE_AUDIT_PASS' in result.stdout
