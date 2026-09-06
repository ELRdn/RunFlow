import importlib.util
from pathlib import Path
import sqlite3
import pytest


def module(name):
    p=Path(__file__).resolve().parents[1]/"scripts"/(name+".py")
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_catalog_query_is_narrow_and_readonly(tmp_path):
    m=module("dump_motion_catalog");p=tmp_path/"meta"
    with sqlite3.connect(p) as db:
        db.execute("CREATE TABLE a (n TEXT,h TEXT,d TEXT,m TEXT)")
        db.executemany("INSERT INTO a VALUES (?,?,?,?)",[("3d/motion/racemain/run", "a"*32,"","_3d_cutt"),("unrelated", "b"*32,"","_3d_cutt")])
    before=p.read_bytes()
    assert m.plain_rows(p)==[("3d/motion/racemain/run","a"*32,"","_3d_cutt")]
    assert p.read_bytes()==before
    m.SQL="DELETE FROM a"
    with pytest.raises(sqlite3.OperationalError):m.plain_rows(p)
    assert p.read_bytes()==before


def test_spring_patch_rejects_wrong_source():
    m=module("prepare_spring_patch")
    with pytest.raises(ValueError,match="structure"):
        m.patch("class Unrelated {}")
