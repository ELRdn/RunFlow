import copy
import os
from pathlib import Path
import sys
import psutil
import pytest
from runflow.shape_resources import system_resources,limit_reason,run


def limits():
    return dict(private_commit_bytes=1024**3,min_available_ram_bytes=0,
        min_commit_headroom_bytes=0,output_bytes=10**7,disk_free_bytes={})


@pytest.mark.parametrize('field,value,reason',[
    ('private_commit_bytes',2*1024**3,'private commit'),('available_ram_bytes',-1,'physical RAM'),
    ('commit_headroom_bytes',-1,'system commit')])
def test_reserves(field,value,reason):
    r=dict(private_commit_bytes=0,available_ram_bytes=10**9,commit_headroom_bytes=10**9,disk_free_bytes={})
    r[field]=value
    assert reason in limit_reason(r,limits(),0,10,0)


def test_time_output_and_disk():
    r=dict(private_commit_bytes=0,available_ram_bytes=10**9,commit_headroom_bytes=10**9,disk_free_bytes={'E:/':10})
    assert limit_reason(r,limits(),10,10,0)=='stage timeout'
    assert limit_reason(r,limits(),0,10,10**8)=='output size limit'
    cap=limits(); cap['disk_free_bytes']={'E:/':20}
    assert limit_reason(r,cap,0,10,0)=='disk reserve: E:/'


@pytest.mark.skipif(os.name!='nt',reason='Windows private commit')
def test_real_windows_commit_and_success(tmp_path):
    r=system_resources()
    assert r['commit_headroom_bytes']==r['commit_limit_bytes']-r['commit_total_bytes']
    r=run([sys.executable,'-c','print("done")'],root=tmp_path,log=tmp_path/'run.log',timeout=5,limits=limits())
    assert r['returncode']==0 and r['reason'] is None and r['termination_verified']


@pytest.mark.skipif(os.name!='nt',reason='Windows private commit')
def test_timeout_descendants_and_preflight(tmp_path):
    marker=tmp_path/'pid.txt'
    code="import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
    r=run([sys.executable,'-c',code,str(marker)],root=tmp_path,log=tmp_path/'run.log',timeout=1.5,limits=limits())
    assert r['reason']=='stage timeout' and r['termination_verified']
    assert not psutil.pid_exists(int(marker.read_text()))
    cap=limits(); cap['min_available_ram_bytes']=10**20
    r=run([sys.executable,'-c','raise Exception()'],root=tmp_path,log=tmp_path/'blocked.log',timeout=2,limits=cap)
    assert not r['launched'] and r['reason']=='physical RAM reserve'


@pytest.mark.skipif(os.name!='nt',reason='Windows jobs')
def test_nested_job_guard(tmp_path):
    inner=tmp_path/'inner'; inner.mkdir()
    code="import sys,json; from pathlib import Path; from runflow.shape_resources import run; p=Path(sys.argv[1]); r=run([sys.executable,'-c','print(123)'],root=p,log=p/'inner.log',timeout=3,limits=json.loads(sys.argv[2])); assert r['returncode']==0 and r['reason'] is None, r"
    r=run([sys.executable,'-c',code,str(inner),__import__('json').dumps(limits())],root=tmp_path,
        log=tmp_path/'outer.log',timeout=5,limits=limits())
    assert r['returncode']==0 and r['reason'] is None,r


def test_delayed_termination_uses_final_process_and_job_evidence(monkeypatch):
    import runflow.shape_resources as resources
    class Job:
        def __init__(self): self.results=iter([False,True])
        def stop(self,timeout=5): return next(self.results)
    class Process:
        def __init__(self,alive): self.alive=alive
        def is_running(self): return self.alive
    monkeypatch.setattr(resources,'terminate_owned',lambda owned:False)
    verified,evidence=resources.stop_owned_job(Job(),{1:Process(False)})
    assert verified and not evidence['initial_known_stopped'] and evidence['final_known_stopped']
    assert not resources.stop_owned_job(Job(),{1:Process(True)})[0]
