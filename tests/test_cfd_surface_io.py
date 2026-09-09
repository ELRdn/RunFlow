import importlib.util
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import pytest

SPEC=importlib.util.spec_from_file_location('cfd_surface_io',Path(__file__).resolve().parents[1]/'scripts/cfd_surface_io.py')
io=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(io)


def test_checker_source_and_cwd_are_local_archive_is_verified(tmp_path,monkeypatch):
    source=tmp_path/'candidate.obj';source.write_bytes(b'v 0.12345678901234567 0 0\n')
    original=source.read_bytes();root=tmp_path/'output';root.mkdir()
    scratch=Path(tempfile.mkdtemp(prefix='runflow-cfd-surface-')).resolve()
    checker=tmp_path/'checker';checker.write_bytes(b'synthetic executable identity')
    monkeypatch.setattr(io.shutil,'disk_usage',lambda _:shutil._ntuple_diskusage(100*1024**3,0,100*1024**3))
    def run(args,**kwargs):
        local=Path(args[-1]);assert local.parent==scratch==kwargs['cwd']
        assert local.read_bytes()==original and args[1]=='-checkSelfIntersection'
        (local.parent/'zone_candidate.vtk').write_text('diagnostic')
        (kwargs['cwd']/'candidate_0.obj').write_text('part')
        kwargs['stdout'].write(b'Surface is not self-intersecting\n')
        return subprocess.CompletedProcess(args,0)
    monkeypatch.setattr(io.subprocess,'run',run)
    try:
        assert io.check_local(source,root,scratch,str(checker))==0
        assert not scratch.exists() and source.read_bytes()==original
        record=io.json.loads((root/'surface-io.json').read_text())
        assert record['complete'] and record['source_sha256']==record['copied_sha256']==io.sha(source)
        assert record['diagnostics']['sha256']==io.sha(root/'surface-diagnostics.tar')
        with tarfile.open(root/'surface-diagnostics.tar') as archive:
            assert set(archive.getnames())=={'zone_candidate.vtk','candidate_0.obj'}
    finally:
        if scratch.exists():shutil.rmtree(scratch)


def test_rejects_unowned_scratch_without_changing_input(tmp_path):
    source=tmp_path/'source.obj';source.write_bytes(b'unchanged')
    with pytest.raises(ValueError,match='Unexpected owned'):
        io.check_local(source,tmp_path,tmp_path)
    assert source.read_bytes()==b'unchanged'


def test_failed_or_interrupted_check_cannot_claim_complete_archive(tmp_path,monkeypatch):
    source=tmp_path/'candidate.obj';source.write_bytes(b'input');root=tmp_path/'out';root.mkdir()
    checker=tmp_path/'checker';checker.write_bytes(b'exe')
    scratch=Path(tempfile.mkdtemp(prefix='runflow-cfd-surface-')).resolve()
    monkeypatch.setattr(io.shutil,'disk_usage',lambda _:shutil._ntuple_diskusage(100*1024**3,0,100*1024**3))
    def interrupted(*args,**kwargs):raise RuntimeError('supervisor interrupted job')
    monkeypatch.setattr(io.subprocess,'run',interrupted)
    try:
        with pytest.raises(RuntimeError):io.check_local(source,root,scratch,str(checker))
        record=io.json.loads((root/'surface-io.json').read_text())
        assert not record['complete'] and record['diagnostics'] is None
        assert scratch.exists() and not (root/'surface-diagnostics.tar').exists()
    finally:shutil.rmtree(scratch)
