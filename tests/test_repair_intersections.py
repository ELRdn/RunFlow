from pathlib import Path
import struct
import sys
import numpy as np
import pytest
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'scripts'))
from check_repair_intersections import binary_stl,intersection_result
from runflow.shape_fullbody import save_arrays


def test_binary_stl_preserves_triangle_order_and_coordinates(tmp_path):
    vertices=np.array([[0,0,0],[1,0,0],[0,1,.123456789]],float)
    save_arrays(tmp_path/'mesh',vertices,[[0,1,2]])
    proof=binary_stl(tmp_path/'mesh',tmp_path/'surface.stl')
    data=(tmp_path/'surface.stl').read_bytes()
    assert len(data)==134 and struct.unpack('<I',data[80:84])[0]==1
    corners=np.frombuffer(data[96:132],dtype='<f4').reshape(3,3)
    np.testing.assert_array_equal(corners,vertices.astype(np.float32))
    assert proof['maximum_corner_rounding_m']<2e-6
    with pytest.raises(FileExistsError): binary_stl(tmp_path/'mesh',tmp_path/'surface.stl')


@pytest.mark.parametrize('log,expected',[
    ('Warning: problems in self-intersection testing later on.',(None,None)),
    ('Checking self-intersection.',(None,None)),
    ('Surface is not self-intersecting',(True,0)),
    ('Surface is self-intersecting at 394 locations.',(False,394)),
    ('Surface is not self-intersecting\nSurface is self-intersecting at 1 locations.',(None,None)),
])
def test_only_explicit_completed_intersection_sentences_count(log,expected):
    assert intersection_result(log)==expected
