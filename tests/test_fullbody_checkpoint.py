import importlib.util
import json
from pathlib import Path
import numpy as np
import pytest
from runflow.shape_fullbody import save_arrays,write,read
from runflow.shape_audit import file_sha

def module():
    repo=Path(__file__).resolve().parents[1]
    source=repo/'scripts/fullbody_voxel_report.py'
    spec=importlib.util.spec_from_file_location('checkpoint_report',source)
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value

def fixture(root):
    for folder in ('cleaned','v600/generated','v600/candidate'):
        save_arrays(root/folder,np.array([[0.,0.,0.],[.002,0.,0.],[0.,.002,0.]]),np.array([[0,1,2]],dtype=np.int32))
    write(root/'request.json',dict(voxel_sizes_um=[900,800,700,600],regions=[]))
    gen=dict(complete=True,voxel_um=600,passes=1,whole_input=True,adaptivity=0,preserve_volume=False,
        cleaned_input_hashes=read(root/'cleaned/cache.json')['output_hashes'],
        output_hashes=read(root/'v600/generated/cache.json')['output_hashes'])
    write(root/'v600/generation.json',gen)
    write(root/'v600/remesh.json',dict(complete=True,repair=dict(max_vertex_shift_m=0)))
    run=dict(stage='v600-remesh',returncode=0,reason='launcher left live descendants',termination_verified=True)
    write(root/'v600-remesh.execution.json',run)
    (root/'v600-remesh.log').write_text('FULLBODY_REMESH_COMPLETE 600')
    proof=dict(complete=True,artifact_usable=True,execution_warning_preserved=True,no_new_remesh=True,
        original_execution_success=False,original_execution_sha256=file_sha(root/'v600-remesh.execution.json'),
        generation_sha256=file_sha(root/'v600/generation.json'),remesh_sha256=file_sha(root/'v600/remesh.json'),
        candidate_hashes=read(root/'v600/candidate/cache.json')['output_hashes'])
    path=root/'verification.json'; write(path,proof)
    write(root/'execution-summary.json',dict(study_id='synthetic',inputs_unchanged=True,records=[run]))
    return path,proof,run

def test_verified_geometry_keeps_original_execution_failure_and_separate_outputs(tmp_path):
    path,proof,run=fixture(tmp_path); report=module()
    initial=report.summarize(tmp_path); original=file_sha(tmp_path/'study-summary.json')
    assert not initial['results']['v600']['generation_complete']
    result=report.summarize(tmp_path,generation_checkpoints={'v600':path},output_suffix='-verified')
    item=result['results']['v600']
    assert item['generation_complete'] and not item['generation_execution_success']
    assert not item['measurement_complete'] and not result['comparison_complete']
    assert item['drag_N'] is None and not item['ranking_eligible']
    assert item['runs'][0]==run and run['reason'] in item['reasons']
    assert file_sha(tmp_path/'study-summary.json')==original
    with pytest.raises(ValueError,match='already exist'):
        report.summarize(tmp_path,generation_checkpoints={'v600':path},output_suffix='-verified')
    with pytest.raises(ValueError,match='separate'):
        report.summarize(tmp_path,generation_checkpoints={'v600':path})

@pytest.mark.parametrize('kind',['timeout','not_stopped','hash','geometry','passes'])
def test_invalid_checkpoint_stops_instead_of_approving_partial_outputs(tmp_path,kind):
    path,proof,run=fixture(tmp_path); report=module()
    if kind in ('timeout','not_stopped'):
        run['reason']='stage timeout' if kind=='timeout' else run['reason']
        if kind=='not_stopped': run['termination_verified']=False
        write(tmp_path/'v600-remesh.execution.json',run)
        proof['original_execution_sha256']=file_sha(tmp_path/'v600-remesh.execution.json')
    elif kind=='hash': proof['remesh_sha256']='0'*64
    elif kind=='geometry':
        with (tmp_path/'v600/candidate/vertices.npy').open('ab') as stream: stream.write(b'changed')
    elif kind=='passes':
        gen=read(tmp_path/'v600/generation.json'); gen['passes']=2
        write(tmp_path/'v600/generation.json',gen); proof['generation_sha256']=file_sha(tmp_path/'v600/generation.json')
    write(path,proof)
    with pytest.raises(ValueError): report.verify_generation_checkpoint(tmp_path,'v600',path)

def test_verified_presentation_preserves_original_files_and_uses_new_summary(tmp_path):
    repo=Path(__file__).resolve().parents[1]
    def load(path,name):
        spec=importlib.util.spec_from_file_location(name,path)
        value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
    fixtures=load(repo/'tests/test_fullbody_review.py','review_fixtures')
    review=load(repo/'scripts/finalize_fullbody_review.py','verified_presentation')
    root,_=fixtures._build_root(tmp_path,[900,800,700,600],with_refs=True)
    summary=read(root/'study-summary.json'); summary['results']['v600']['generation_checkpoint']={'artifact_complete':True}
    write(root/'study-summary-verified.json',summary)
    (root/'FINAL_REVIEW.md').write_text('Original warning history')
    old=file_sha(root/'study-summary.json')
    review.create(root,output_suffix='-verified')
    assert file_sha(root/'study-summary.json')==old
    assert (root/'FINAL_REVIEW.md').read_text()=='Original warning history'
    text=(root/'FINAL_REVIEW-verified.md').read_text(encoding='utf-8')
    assert 'review-final-verified/comparison.png' in text and '(REVIEW-verified.md)' in text
    assert '完了（出力再検証）' in text and '元の実行を成功へ変更していない' in text
    provenance=read(root/'review-final-verified/provenance.json')
    assert provenance['source_summary_sha256']==file_sha(root/'study-summary-verified.json')
