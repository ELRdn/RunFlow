from pathlib import Path
import subprocess
import pytest


def test_pinned_blender_local_remesh_measurement(tmp_path):
    root=Path(__file__).resolve().parents[1]
    blender=root/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
    if not blender.exists(): pytest.skip('Pinned Blender unavailable')
    result=subprocess.run([str(blender),'--background','--factory-startup','--threads','4',
        '--python-exit-code','2','--python',str(root/'tests/blender_local_voxel.py'),'--',str(tmp_path/'study')],
        capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'BLENDER_LOCAL_VOXEL_PASS' in result.stdout
