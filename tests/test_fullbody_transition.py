import importlib.util
import os
import subprocess
from pathlib import Path
import numpy as np
import pytest
from runflow.shape_fullbody import study_profile,write,save_arrays
from runflow.shape_audit import file_sha

REPO=Path(__file__).resolve().parents[1]

def test_blender_transition_four_sizes(tmp_path):
    blender=REPO/'.tools/blender/blender-4.2.23-windows-x64/blender.exe'
    if not blender.exists(): pytest.skip('Pinned Blender missing')
    result=subprocess.run([str(blender),'--background','--factory-startup','--threads','4','--python-exit-code','2',
        '--python',str(REPO/'tests/blender_fullbody_voxel.py'),'--',str(tmp_path/'study')],
        env={**os.environ,'RUNFLOW_TEST_VOXELS_UM':'900,800,700,600'},capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'BLENDER_FULLBODY_PASS' in result.stdout

def module(name):
    spec=importlib.util.spec_from_file_location(name,REPO/'scripts'/(name+'.py'))
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value

def test_transition_profile_preserves_old_profile_and_rejects_unapproved_or_wrong_units():
    assert study_profile({})==((1000,500,250,100),(900,2700,5400,12600))
    assert study_profile(dict(voxel_sizes_um=[900,800,700,600]))==((900,800,700,600),(2700,)*4)
    for values in ([.9,.8,.7,.6],[900,800,700,100],[900,900,700,600],[600,700,800,900]):
        with pytest.raises(ValueError): study_profile(dict(voxel_sizes_um=values))

def test_new_profile_results_do_not_include_old_cases_or_failed_generated_arrays(tmp_path):
    write(tmp_path/'request.json',dict(voxel_sizes_um=[900,800,700,600],regions=[]))
    write(tmp_path/'execution-summary.json',dict(study_id='synthetic',inputs_unchanged=True,records=[
        dict(stage='v900-remesh',returncode=0,reason=None,termination_verified=False)]))
    write(tmp_path/'v900/remesh.json',dict(complete=True))
    value=module('fullbody_voxel_report').summarize(tmp_path)
    assert set(value['results'])=={'v900','v800','v700','v600'}
    assert not value['results']['v900']['generation_complete']
    assert not value['comparison_complete'] and value['human_adoption'] is None

def test_common_input_must_match_saved_binary_geometry(tmp_path):
    runner=module('run_fullbody_voxel_comparison')
    write(tmp_path/'reference.json',dict(output_hashes={'vertices.npy':'fixed','triangles.npy':'fixed'}))
    req=dict(inputs={'shared-cleaned-cache':dict(path=str(tmp_path/'reference.json'),sha256=file_sha(tmp_path/'reference.json'))})
    write(tmp_path/'cleaned/cache.json',dict(output_hashes={'vertices.npy':'changed','triangles.npy':'fixed'}))
    with pytest.raises(ValueError,match='differs'): runner.verify_common_preparation(tmp_path,req)
    assert not (tmp_path/'common-input-match.json').exists()

def test_reference_archive_checks_hashes_and_does_not_copy_geometry(tmp_path):
    runner=module('run_fullbody_voxel_comparison')
    source=tmp_path/'input.json'; source.write_text('{}')
    def request(destination,hash):
        return dict(reference_cases=[dict(folder='references/v1000',source_files=[
            dict(path=str(source),sha256=hash,destination=destination)])])
    with pytest.raises(ValueError,match='not allowed'):
        runner.archive_references(tmp_path,request('candidate/vertices.npy',file_sha(source)))
    with pytest.raises(ValueError,match='hash'):
        runner.archive_references(tmp_path,request('result.json','0'*64))
    runner.archive_references(tmp_path,request('result.json',file_sha(source)))
    assert (tmp_path/'references/v1000/result.json').read_bytes()==source.read_bytes()
