from pathlib import Path
import numpy as np
import pytest
from runflow import cfd
from runflow.core import read, write, file_hash
from runflow.cfd_reuse import seal, reuse, FILES
from runflow.cfd_surface import prepare_surface
from runflow.shape_fullbody import save_arrays


def prepared(tmp_path,monkeypatch):
    monkeypatch.setattr(cfd,'REPO',tmp_path)
    v=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],dtype=float)
    f=np.array([[0,2,1],[0,1,3],[1,2,3],[0,3,2]],dtype=np.int32)
    source=tmp_path/'source';save_arrays(source,v,f)
    old=tmp_path/'private/old';old.mkdir(parents=True);prepare_surface(old,source)
    write(old/'state.json',dict(status='TIMEOUT',completed_epoch=10))
    for name in ('result.json','provisional-receipt.json','tool-pins.json'):write(old/name,{'synthetic':True})
    return old


def test_reuse_copies_exact_verified_surface_and_preserves_failed_attempt(tmp_path,monkeypatch):
    old=prepared(tmp_path,monkeypatch);proof=seal(old);path=tmp_path/'proof.json';write(path,proof)
    new=tmp_path/'private/new';new.mkdir()
    reuse(new,path,proof['input_cache_sha256'])
    assert all(file_hash(old/'geometry'/name)==file_hash(new/'geometry'/name) for name in FILES)
    assert read(old/'state.json')==dict(status='TIMEOUT',completed_epoch=10)
    assert not read(new/'geometry-reuse.json')['regenerated']
    assert seal(old)==proof


def test_reuse_rejects_modified_array_and_wrong_original(tmp_path,monkeypatch):
    old=prepared(tmp_path,monkeypatch);proof=seal(old);path=tmp_path/'proof.json';write(path,proof)
    new=tmp_path/'private/new';new.mkdir()
    with pytest.raises(ValueError,match='proof/input changed'):reuse(new,path,'f'*64)
    assert not (new/'geometry').exists()
    with (old/'geometry/surface-cache/vertices.npy').open('ab') as stream:stream.write(b'changed')
    with pytest.raises(ValueError,match='cache hash mismatch'):reuse(new,path,proof['input_cache_sha256'])
    assert not (new/'geometry').exists()


def test_cannot_reuse_active_attempt(tmp_path,monkeypatch):
    old=prepared(tmp_path,monkeypatch);write(old/'state.json',dict(status='PREPARING'))
    with pytest.raises(ValueError,match='completed failed'):seal(old)
