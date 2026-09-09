"""Create a fresh private campaign from the pinned, completed repair comparison."""
import argparse
import json
from pathlib import Path
import sys
import time
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from runflow.shape_fullbody import read,write,private_root
from runflow.shape_audit import file_sha,load_surface
from runflow.shape_repair import validate
from runflow.local_repair_contract import SETTINGS,configuration_id
from runflow.local_geometry import tools_manifest,ROOT as GEOMETRY

def prepare(old,output):
    started=time.monotonic();old=Path(old).resolve();output=private_root(output,REPO)
    request=read(old/'request.json');validate(request);tools_manifest()
    surfaces={'source':old/'source','cleaned':old/'cleaned','base900':old/'v900/candidate',
        'reference1000':old/'v1000/candidate','raw_carve64':old/'v900-raycarve2/generated',
        'old_carve32':old/'v900-raycarve2/candidate'}
    refs={};pins={k:v['sha256'] for k,v in request['inputs'].items()}
    for name,path in surfaces.items():
        load_surface(path)
        meta=read(path/'cache.json');refs[name]=dict(path=str(path),cache_sha256=file_sha(path/'cache.json'),hashes=meta['output_hashes'])
        pins[name+'-cache']=refs[name]['cache_sha256']
    tools={'native-build':file_sha(GEOMETRY/'build.json'),'python':file_sha(sys.executable),
        'manifold-install':file_sha(REPO/'.tools/manifold3d-3.5.2/install.json'),
        'plan-code':file_sha(__file__),'contract':file_sha(REPO/'src/runflow/local_repair_contract.py')}
    output.mkdir(exist_ok=False)
    settings=dict(SETTINGS)
    value=dict(settings=settings,configuration_id=configuration_id(settings,pins,tools),input_hashes=pins,
        source_study=str(old),source_request_sha256=file_sha(old/'request.json'),input_surfaces=refs,
        old_inputs=request['inputs'],regions=request['regions'],tool_hashes=tools,
        target_storage='E:/RunFlowPrivate/phase1-validation',operational_output=str(output),
        candidates=[],scientific_status='UNAPPROVED',ranking_eligible=False,human_adoption=None)
    write(output/'request.json',value)
    write(output/'execution.json',dict(records=[dict(stage='diagnosis',task='prepare',elapsed_s=time.monotonic()-started,
        complete=True,launched=False,termination_verified=True)],finished=False,cfds_run=0,drag_N=None,Cd=None,CdA_m2=None))
    print('LOCAL_REPAIR_PREPARED',output,flush=True)
    return value

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-study',type=Path,default=Path('E:/RunFlowPrivate/phase1-validation/fullbody-repair-003'));p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();prepare(a.source_study,a.output)

if __name__=='__main__':main()
