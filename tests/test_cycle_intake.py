import importlib.util
from pathlib import Path
import sys
import pytest
from runflow.core import write

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
from finalize_cycle_capture import intake_equivalence
from accepted_capture import PINNED_GAME_INPUTS


def inputs(tmp_path):
    old=tmp_path/'old';new=tmp_path/'new';old.mkdir();new.mkdir()
    record=dict(**PINNED_GAME_INPUTS,assets=[dict(source_path='model',sha256='a'*64,locator='input')])
    for folder in (old,new):
        write(folder/'inputs-0.json',record)
        for name in ('inventory-0.json','transforms-0.json','adoption-input.json'):write(folder/name,{'constant':True})
    return old,new,record


def test_new_index_is_not_falsely_called_same_game_build(tmp_path):
    old,new,record=inputs(tmp_path);record['meta_sha256']='b'*64;write(new/'inputs-0.json',record)
    value=intake_equivalence(new,old)
    assert not value['metadata_database_identical']
    assert value['materialized_assets_identical']
    assert value['current_client_build']=='UNVERIFIED'
    assert value['human_review'] is None and value['scientific_approval'] is None


@pytest.mark.parametrize('changed',['assets','master','runtime'])
def test_new_intake_stops_on_relevant_changes(tmp_path,changed):
    old,new,record=inputs(tmp_path)
    if changed=='assets':record['assets'][0]['sha256']='c'*64
    elif changed=='master':record['master_sha256']='c'*64
    else:write(new/'transforms-0.json',{'changed':True})
    write(new/'inputs-0.json',record)
    with pytest.raises(ValueError):intake_equivalence(new,old)
