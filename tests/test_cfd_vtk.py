import struct
import pytest
from runflow.cfd_vtk import read_vtk


def binary_fixture():
    return (b'# vtk DataFile Version 2.0\nsynthetic\nBINARY\nDATASET UNSTRUCTURED_GRID\nPOINTS 4 float\n'
        +struct.pack('>12f',0,0,0,1,0,0,0,1,0,0,0,1)
        +b'\nCELLS 1 5\n'+struct.pack('>5i',4,0,1,2,3)
        +b'\nCELL_TYPES 1\n'+struct.pack('>i',10)
        +b'\nCELL_DATA 1\nFIELD attributes 3\ncellID 1 1 int\n'+struct.pack('>i',7)
        +b'\np 1 1 float\n'+struct.pack('>f',2)
        +b'\nU 3 1 float\n'+struct.pack('>3f',-20,0,0)+b'\n')


def test_big_endian_binary_preserves_p_and_velocity_units(tmp_path):
    file=tmp_path/'internal.vtk'; file.write_bytes(binary_fixture())
    points,cells,fields=read_vtk(file)
    assert points[1]==(1,0,0) and cells==[[0,1,2,3]]
    assert fields=={'p':[(2,)],'U':[(-20,0,0)]}


def test_truncated_binary_field_is_rejected(tmp_path):
    file=tmp_path/'internal.vtk'; file.write_bytes(binary_fixture()[:-3])
    with pytest.raises(ValueError,match='Truncated binary'): read_vtk(file)


def test_nonfinite_binary_field_is_rejected(tmp_path):
    file=tmp_path/'internal.vtk'
    file.write_bytes(binary_fixture().replace(struct.pack('>f',-20),struct.pack('>f',float('nan'))))
    with pytest.raises(ValueError,match='Non-finite'): read_vtk(file)
