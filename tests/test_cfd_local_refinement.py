import copy
from pathlib import Path
import sys
import pytest
from runflow.core import read,digest
from runflow.cfd_contracts import validate
from runflow.cfd_case import build
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import cfd_worker


def protocol():
    p=read(Path(__file__).parents[1]/'configs/cfd.phase1-provisional.json')
    p['diagnostic_refinement']=dict(reason_id='oguri_coat_tip_flow_reversal_001',
        source_snapshot_sha256='a'*64,box_min_m=[.1,.2,.3],box_max_m=[.4,.5,.6],level=6)
    return p


def test_local_volume_refinement_preserves_surface_physics_domain_and_limits(tmp_path):
    p=protocol();validate('protocol',p);old=copy.deepcopy(p);old.pop('diagnostic_refinement')
    ref={'files':{'tutorial/system/'+n:'// pinned' for n in ('fvSolution','fvSchemes','meshQualityDict')}}
    source={'vertices':[[0,0,0],[1,1,1]]};a=tmp_path/'old';b=tmp_path/'new'
    build(a,source,old,ref);info=build(b,source,p,ref)
    for path in a.rglob('*'):
        if path.is_file() and path.name!='snappyHexMeshDict':assert path.read_bytes()==(b/path.relative_to(a)).read_bytes()
    text=(b/'system/snappyHexMeshDict').read_text()
    assert 'coatTip {mode inside; level 6;}' in text and 'level (5 5);' in text
    assert info['diagnostic_volume_refinement']==p['diagnostic_refinement'] and digest(p)!=digest(old)
    for key in ('geometry','mesh','limits','convergence'):assert p[key]==old[key]


@pytest.mark.parametrize('field,value',[('level',5),('level',8),('box_min_m',[0,0]),('box_min_m',[.4,.5,.6]),('source_snapshot_sha256','unknown')])
def test_unplanned_local_refinement_is_rejected(field,value):
    p=protocol();p['diagnostic_refinement'][field]=value
    with pytest.raises(ValueError):validate('protocol',p)


@pytest.mark.parametrize('log,expected',[
    ('Refinement level 6 for all cells inside coatTip\nSelected for internal refinement : 0 cells',True),
    ('Refinement level 6 for all cells inside coatTip\nSelected for internal refinement : 1 cells',False),
    ('Refinement level 5 for all cells inside coatTip\nSelected for internal refinement : 0 cells',False),
    ('Selected for internal refinement : 0 cells',False),
])
def test_local_grid_requires_recognized_region_and_completed_refinement(log,expected):
    evidence=cfd_worker.region_refinement_evidence(log,protocol())
    assert evidence['diagnostic_refinement_reached'] is expected


def test_local_grid_target_mismatch_stops_before_creating_output(tmp_path,monkeypatch):
    from runflow import cfd_provisional
    from runflow.core import write
    monkeypatch.setattr(cfd_provisional.cfd,'private',lambda p:Path(p))
    monkeypatch.setattr(cfd_provisional,'verify_authorization',lambda r:None) # separately covered by authorization tests
    write(tmp_path/'protocol.json',protocol())
    write(tmp_path/'receipt.json',dict(source_snapshot_sha256='b'*64))
    with pytest.raises(ValueError,match='different adopted snapshot'):
        cfd_provisional.prepare(tmp_path/'receipt.json',tmp_path/'protocol.json',tmp_path/'output')
    assert not (tmp_path/'output').exists()
