"""Completion races and accounting must not weaken process termination."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import psutil
import pytest
from runflow import shape_resources as resources

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows Job Object completion')

def limits():
    return dict(private_commit_bytes=1024**3,min_available_ram_bytes=0,
        min_commit_headroom_bytes=0,output_bytes=10**7,disk_free_bytes={})

def test_persistent_detached_child_is_stopped_and_remains_a_failure(tmp_path):
    marker=tmp_path/'pid.txt'
    code="import subprocess,sys; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); Path(sys.argv[1]).write_text(str(p.pid))"
    result=resources.run([sys.executable,'-c',code,str(marker)],root=tmp_path,
        log=tmp_path/'leftover.log',timeout=5,limits=limits())
    assert result['reason']=='launcher left live descendants' and result['termination_verified']
    assert not psutil.pid_exists(int(marker.read_text()))

def test_completed_process_is_not_failed_by_one_delayed_job_count(tmp_path,monkeypatch):
    original=resources.OwnedJob
    class DelayedAccountingJob(original):
        delayed=False
        def active(self):
            actual=super().active()
            if actual==0 and not self.delayed:
                self.delayed=True
                return 1
            return actual
    monkeypatch.setattr(resources,'OwnedJob',DelayedAccountingJob)
    result=resources.run([sys.executable,'-c','print("complete",flush=True)'],root=tmp_path,
        log=tmp_path/'completion.log',timeout=5,limits=limits())
    assert result['returncode']==0 and result['termination_verified']
    assert result['reason'] is None,result

def test_aggregate_commit_is_limited_even_if_owned_group_is_small():
    sample=dict(private_commit_bytes=1,accounted_private_commit_bytes=2*1024**3,
        available_ram_bytes=10**9,commit_headroom_bytes=10**9,disk_free_bytes={})
    assert resources.limit_reason(sample,limits(),0,10,0)=='private commit limit'

def test_external_group_is_observed_but_never_terminated(tmp_path):
    marker=tmp_path/'external-ready'
    code="import time,sys; from pathlib import Path; data=bytearray(1024*1024*16); Path(sys.argv[1]).write_text('ready'); time.sleep(30)"
    other=psutil.Popen([sys.executable,'-c',code,str(marker)],creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        import time
        end=time.monotonic()+5
        while not marker.exists() and time.monotonic()<end: time.sleep(.01)
        assert marker.exists()
        cap={**limits(),'accounted_external_roots':[dict(pid=other.pid,created_at=other.create_time())]}
        result=resources.run([sys.executable,'-c','import time; time.sleep(30)'],root=tmp_path,
            log=tmp_path/'accounting.log',timeout=.6,limits=cap)
        assert result['reason']=='stage timeout' and result['termination_verified']
        assert other.is_running() and all(p['pid']!=other.pid for p in result['owned_processes'])
        telemetry=[json.loads(x) for x in (tmp_path/'accounting.resources.jsonl').read_text().splitlines()]
        assert max(s['external_private_commit_bytes'] for s in telemetry)>16*1024**2
        assert all(s['accounted_private_commit_bytes']==s['private_commit_bytes']+s['external_private_commit_bytes'] for s in telemetry)
        cap['accounted_external_roots'][0]['created_at']-=10
        result=resources.run([sys.executable,'-c','print(1)'],root=tmp_path,
            log=tmp_path/'reused.log',timeout=5,limits=cap)
        assert result['reason'] is None
        assert all(json.loads(x)['external_private_commit_bytes']==0 for x in (tmp_path/'reused.resources.jsonl').read_text().splitlines())
    finally:
        other.terminate(); other.wait(timeout=5)
