from pathlib import Path
import subprocess

import pytest


def test_pinned_blender_exported_topology_and_local_weld():
    root = Path(__file__).resolve().parents[1]
    blender = root/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
    if not blender.exists(): pytest.skip('Pinned Blender is not installed')
    result = subprocess.run([str(blender), '--background', '--factory-startup', '--threads', '4',
        '--python-exit-code', '2', '--python', str(root/'tests/blender_cfd_geometry.py')],
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'BLENDER_CFD_GEOMETRY_PASS' in result.stdout
