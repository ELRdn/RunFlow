import copy
import importlib.util
from pathlib import Path
import pytest
from runflow.core import write

spec=importlib.util.spec_from_file_location('direct',Path(__file__).resolve().parents[1]/'scripts/compare_direct_capture.py')
direct=importlib.util.module_from_spec(spec)
spec.loader.exec_module(direct)


@pytest.mark.parametrize('problem',['missing','static','translation_only','time','valid'])
def test_real_sequence_gate(snapshot,tmp_path,problem):
    for i in range(15 if problem=='missing' else 16):
        s=copy.deepcopy(snapshot)
        s['time_s']=i/16 if problem!='time' else 0
        if problem=='translation_only':
            for v in s['joints'].values(): v[0]+=i*.01
        elif problem in ('valid','missing','time'):
            s['joints']['left_foot'][0]+=.01*i
            s['joints']['right_foot'][0]-=.01*i
        write(tmp_path/f'f{i:02d}.snapshot.json',s)
    if problem=='valid': assert len(direct.frames(tmp_path)[1])==16
    else:
        with pytest.raises(ValueError): direct.frames(tmp_path)


@pytest.mark.parametrize('problem',['valid','changed','missing_assets','bad_hash'])
def test_capture_input_provenance(tmp_path,problem):
    record=dict(meta_sha256='a'*64,master_sha256='b'*64,
        assets=[dict(source_path='motion',sha256='c'*64)],
        capture_scripts=[dict(name='Capture.cs',sha256='d'*64)])
    write(tmp_path/'inputs-0.json',record)
    if problem=='changed': record['assets'][0]['sha256']='e'*64
    elif problem=='missing_assets': record['assets']=[]
    elif problem=='bad_hash': record['meta_sha256']='unknown'
    write(tmp_path/'inputs-1.json',record)
    if problem=='valid': assert direct.verify_inputs(tmp_path)['loaded_asset_bundles']==1
    else:
        with pytest.raises(ValueError): direct.verify_inputs(tmp_path)
