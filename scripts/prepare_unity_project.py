"""Prepare an isolated pinned checkout; copies local configuration without printing it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from prepare_spring_patch import UPSTREAM_SHA256, patch, COMMIT


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--viewer-config',type=Path,required=True)
    a=p.parse_args()
    repo=Path(__file__).resolve().parents[1]
    project=a.project.resolve()
    if not project.is_relative_to(repo/'.tools'): raise ValueError('Isolated .tools project required')
    version=(project/'ProjectSettings/ProjectVersion.txt').read_text()
    if '2022.3.62f1' not in version or '4af31df58517' not in version: raise ValueError('Wrong Unity project version')
    source=project/'Assets/Scripts/DynamicBone/Scripts/DynamicBone.cs'
    original=source.read_bytes()
    if hashlib.sha256(original).hexdigest()!=UPSTREAM_SHA256: raise ValueError('Wrong or already patched source')
    # Config may contain keys. Keep it in the ignored project; never include it in provenance.
    config=json.loads(a.viewer_config.read_text(encoding='utf-8-sig'))
    config.update(Language=1,WorkMode=0,Region=1,VmdKeyReductionLevel=1,DownloadMissingResources=False)
    (project/'Config.json').write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8')
    source.write_text(patch(original.decode('utf-8-sig')),encoding='utf-8',newline='\n')
    target=project/'Assets/RunFlow'
    target.mkdir(exist_ok=False)
    files={}
    for path in sorted((repo/'integrations/unity').glob('*.cs')):
        shutil.copyfile(path,target/path.name)
        files[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (project/'runflow-patch.json').write_text(json.dumps({'commit':COMMIT,'unity':'2022.3.62f1',
        'scripts':files,'dynamic_bone_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'runtime_verified':False},indent=2))
    print('PROJECT_PREPARED_RUNTIME_UNVERIFIED')


if __name__=='__main__': main()
