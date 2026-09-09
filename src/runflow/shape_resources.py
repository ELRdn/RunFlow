"""Study-only resource guard. Windows commit is not the page-file size."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time

import psutil
from runflow.cfd_guard import directory_bytes

GIB = 1024 ** 3


class OwnedJob:
    """Kernel-owned process tree, including children missed between polling ticks."""
    def __init__(self):
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.CreateJobObjectW.restype=wintypes.HANDLE
        self.api.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        self.api.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        self.api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        self.api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.api.OpenProcess.restype=wintypes.HANDLE
        self.api.CloseHandle.argtypes=[wintypes.HANDLE]
        self.api.TerminateJobObject.argtypes=[wintypes.HANDLE,wintypes.UINT]
        self.api.QueryInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
        class Basic(ctypes.Structure):
            _fields_=[('ProcessTime',ctypes.c_longlong),('JobTime',ctypes.c_longlong),('Flags',wintypes.DWORD),
                ('MinWorkingSet',ctypes.c_size_t),('MaxWorkingSet',ctypes.c_size_t),('ActiveLimit',wintypes.DWORD),
                ('Affinity',ctypes.c_size_t),('Priority',wintypes.DWORD),('Scheduling',wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_=[('Basic',Basic),('Io',ctypes.c_ulonglong*6),('ProcessMemory',ctypes.c_size_t),
                ('JobMemory',ctypes.c_size_t),('PeakProcessMemory',ctypes.c_size_t),('PeakJobMemory',ctypes.c_size_t)]
        self.handle=self.api.CreateJobObjectW(None,None)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        settings=Extended(); settings.Basic.Flags=0x2000  # KILL_ON_JOB_CLOSE, no breakaway
        if not self.api.SetInformationJobObject(self.handle,9,ctypes.byref(settings),ctypes.sizeof(settings)):
            self.close(); raise ctypes.WinError(ctypes.get_last_error())
    def assign(self,pid):
        handle=self.api.OpenProcess(0x0100|0x0001,False,pid)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle,handle): raise ctypes.WinError(ctypes.get_last_error())
        finally: self.api.CloseHandle(handle)
    def active(self):
        class Accounting(ctypes.Structure):
            _fields_=[('User',ctypes.c_longlong),('Kernel',ctypes.c_longlong),('PeriodUser',ctypes.c_longlong),
                ('PeriodKernel',ctypes.c_longlong),('Faults',wintypes.DWORD),('Total',wintypes.DWORD),
                ('Active',wintypes.DWORD),('Terminated',wintypes.DWORD)]
        value=Accounting()
        if not self.api.QueryInformationJobObject(self.handle,1,ctypes.byref(value),ctypes.sizeof(value),None):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.Active
    def stop(self,timeout=5):
        self.api.TerminateJobObject(self.handle,1)
        end=time.monotonic()+timeout
        while self.active() and time.monotonic()<end: time.sleep(.05)
        return self.active()==0
    def close(self):
        if self.handle: self.api.CloseHandle(self.handle); self.handle=None


def system_resources():
    ram = psutil.virtual_memory()
    result = dict(available_ram_bytes=ram.available, total_ram_bytes=ram.total)
    if os.name == 'nt':
        class PerformanceInfo(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in
                ('CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal', 'PhysicalAvailable',
                 'SystemCache', 'KernelTotal', 'KernelPaged', 'KernelNonpaged', 'PageSize')] + [
                (n, wintypes.DWORD) for n in ('HandleCount', 'ProcessCount', 'ThreadCount')]
        value = PerformanceInfo(); value.cb = ctypes.sizeof(value)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(value), value.cb):
            raise OSError('GetPerformanceInfo failed')
        result.update(commit_total_bytes=value.CommitTotal * value.PageSize,
                      commit_limit_bytes=value.CommitLimit * value.PageSize,
                      commit_headroom_bytes=(value.CommitLimit-value.CommitTotal)*value.PageSize)
    else:
        raise RuntimeError('This study requires Windows commit accounting')
    return result


def limit_reason(resources, limits, elapsed_s, timeout, output_bytes):
    if elapsed_s >= timeout: return 'stage timeout'
    if resources.get('accounted_private_commit_bytes',resources['private_commit_bytes']) > limits['private_commit_bytes']: return 'private commit limit'
    if resources['available_ram_bytes'] < limits['min_available_ram_bytes']: return 'physical RAM reserve'
    if resources['commit_headroom_bytes'] < limits['min_commit_headroom_bytes']: return 'system commit reserve'
    if output_bytes > limits['output_bytes']: return 'output size limit'
    for drive, minimum in limits['disk_free_bytes'].items():
        if resources['disk_free_bytes'][drive] < minimum: return 'disk reserve: '+drive
    return None


def terminate_owned(owned):
    targets = list(owned.values())
    # Recollect while the launcher is still alive, then terminate descendants first.
    for process in targets:
        try:
            for child in process.children(recursive=True): owned[(child.pid,child.create_time())] = child
        except psutil.NoSuchProcess: pass
    targets = list(owned.values())[::-1]
    for process in targets:
        try: process.terminate()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(targets, timeout=2)
    for process in alive:
        try: process.kill()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(alive, timeout=3)
    return not alive


def stop_owned_job(job,owned):
    """Report final liveness, while preserving an initially delayed stop result."""
    attempts=dict(initial_job_empty=job.stop(),initial_known_stopped=terminate_owned(owned))
    attempts['final_job_empty']=job.stop(timeout=20)
    attempts['final_known_stopped']=all(not p.is_running() for p in owned.values())
    return attempts['final_job_empty'] and attempts['final_known_stopped'],attempts


def run(command, *, root, log, timeout, limits, cwd=None, env=None):
    start = time.monotonic(); owned = {}; reason = None; process = None
    peak_rss = peak_commit = peak_threads = 0; peak_output = directory_bytes(root)
    samples = Path(log).with_suffix('.resources.jsonl')
    cpu_totals={}; previous_cpu=0.; previous_sample=start; termination_attempts=[]
    def snapshot():
        nonlocal previous_cpu,previous_sample
        value = system_resources()
        value['disk_free_bytes'] = {d:psutil.disk_usage(d).free for d in limits['disk_free_bytes']}
        rss = commit = threads = 0
        if process is not None:
            try:
                for child in [process]+process.children(recursive=True):
                    owned[(child.pid,child.create_time())] = child
            except psutil.NoSuchProcess: pass
        for child in list(owned.values()):
            try:
                if not child.is_running(): continue  # also excludes a reused PID
                m = child.memory_info(); rss += m.rss; commit += m.private; threads += child.num_threads()
                cpu=child.cpu_times(); cpu_totals[(child.pid,child.create_time())]=cpu.user+cpu.system
            except psutil.NoSuchProcess: pass
        now=time.monotonic(); cpu_sum=sum(cpu_totals.values()); logical=psutil.cpu_count()
        value.update(rss_bytes=rss, private_commit_bytes=commit, threads=threads,
                     elapsed_s=now-start,cpu_seconds_observed=cpu_sum,logical_cpu_count=logical,
                     study_cpu_percent=100*max(0.,cpu_sum-previous_cpu)/max(now-previous_sample,1e-6)/logical)
        previous_cpu=cpu_sum; previous_sample=now
        # Other explicitly identified study workers are accounted read-only.
        # They are never added to our termination set or condition cost totals.
        external={}
        for root_spec in limits.get('accounted_external_roots',[]):
            try:
                other=psutil.Process(root_spec['pid'])
                if abs(other.create_time()-root_spec['created_at'])>=.01: continue
                for item in [other]+other.children(recursive=True):
                    key=(item.pid,item.create_time())
                    if key not in owned: external[key]=item
            except psutil.NoSuchProcess: pass
        extra_commit=extra_rss=0
        for item in external.values():
            try:
                if not item.is_running(): continue
                info=item.memory_info(); extra_commit+=info.private; extra_rss+=info.rss
            except psutil.NoSuchProcess: pass
        value.update(external_private_commit_bytes=extra_commit,external_rss_bytes=extra_rss,
            accounted_private_commit_bytes=commit+extra_commit)
        return value
    verified = True; code = None; job=None
    with Path(log).open('wb') as stream, samples.open('w', encoding='utf-8') as telemetry:
        try:
            initial = snapshot()
            reason = limit_reason(initial, limits, 0, timeout, peak_output)
            telemetry.write(json.dumps(initial)+'\n'); telemetry.flush()
            if reason is None:
                job=OwnedJob()
                process = psutil.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                owned[(process.pid,process.create_time())] = process
                job.assign(process.pid)
                if env and env.get('RUNFLOW_CPU_COUNT'):
                    process.cpu_affinity(psutil.Process().cpu_affinity()[:int(env['RUNFLOW_CPU_COUNT'])])
                last_size = 0; resource_failure_since=None
                while True:
                    s = snapshot(); elapsed = time.monotonic()-start
                    peak_rss=max(peak_rss,s['rss_bytes']); peak_commit=max(peak_commit,s['private_commit_bytes'])
                    peak_threads=max(peak_threads,s['threads'])
                    if elapsed-last_size >= 5:
                        peak_output=max(peak_output,directory_bytes(root)); last_size=elapsed
                    telemetry.write(json.dumps(s)+'\n'); telemetry.flush()
                    reason=limit_reason(s,limits,elapsed,timeout,peak_output)
                    # The outer watchdog gives the stage guard time to stop its payload and
                    # save the failure. Timeouts and preflight checks remain immediate.
                    if reason and reason!='stage timeout' and limits.get('resource_grace_s',0)>0:
                        if resource_failure_since is None: resource_failure_since=elapsed
                        if elapsed-resource_failure_since<limits['resource_grace_s']: reason=None
                    elif reason is None: resource_failure_since=None
                    if reason or process.poll() is not None: break
                    time.sleep(.5)
                code=process.poll()
                if reason:
                    verified,attempts=stop_owned_job(job,owned); termination_attempts.append(attempts)
                    code=process.wait(timeout=5)
                else:
                    # Let OS accounting / console hosts settle after the payload exits.
                    # This observation consumes the existing stage budget. Persistent
                    # descendants are still killed and reported as a failed execution.
                    exit_deadline=min(start+timeout,time.monotonic()+2)
                    while True:
                        live=[]
                        for child in owned.values():
                            try:
                                if child.pid != process.pid and child.is_running(): live.append(child)
                            except psutil.NoSuchProcess: pass
                        if not live and not job.active(): break
                        left=exit_deadline-time.monotonic()
                        if left<=0:
                            reason='launcher left live descendants'
                            verified,attempts=stop_owned_job(job,owned); termination_attempts.append(attempts)
                            break
                        time.sleep(min(.02,left))
        except BaseException as exc:
            verified=terminate_owned(owned)
            if job is not None: verified=job.stop() and verified
            reason=f'guard failure: {type(exc).__name__}: {exc}'
            if process is not None: code=process.poll()
        finally:
            if job is not None: job.close()
        peak_output=max(peak_output,directory_bytes(root))
        if reason is None and peak_output>limits['output_bytes']: reason='output size limit'
    return dict(command=command,returncode=code,reason=reason,elapsed_s=time.monotonic()-start,
        peak_rss_bytes=peak_rss,peak_private_commit_bytes=peak_commit,peak_threads=peak_threads,
        peak_output_bytes=peak_output,termination_verified=verified,launched=process is not None,
        owned_processes=[dict(pid=pid,created_at=created) for pid,created in owned],
        termination_attempts=termination_attempts)
