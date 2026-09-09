"""Bounded Windows/local subprocesses; Linux CFD has its own process-group guard."""
import subprocess
import time
from pathlib import Path
import psutil


def directory_bytes(root):
    return sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())


def stop_tree(process):
    try: children=process.children(recursive=True)
    except psutil.NoSuchProcess: children=[]
    targets=children+[process]
    for child in targets:
        try: child.terminate()
        except psutil.NoSuchProcess: pass
    _,alive=psutil.wait_procs(targets,timeout=2)
    for child in alive:
        try: child.kill()
        except psutil.NoSuchProcess: pass
    _,alive=psutil.wait_procs(alive,timeout=3)
    return not alive


def run(command, *, log, root, timeout, memory_bytes, output_bytes, cwd=None, input_bytes=None, cancel_path=None):
    started=time.monotonic(); peak=0; peak_bytes=0; reason=None; terminated=None
    if timeout<=0: raise ValueError('No stage time remaining')
    flags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess,'CREATE_NO_WINDOW') else 0
    with Path(log).open('wb') as stream:
        process=psutil.Popen(command,stdout=stream,stderr=subprocess.STDOUT,cwd=cwd,creationflags=flags,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL)
        try:
            if input_bytes is not None:
                process.stdin.write(input_bytes); process.stdin.close()
            while process.poll() is None:
                try:
                    used=sum(p.memory_info().rss for p in [process]+process.children(recursive=True) if p.is_running())
                    peak=max(peak,used)
                except psutil.NoSuchProcess: pass
                try: peak_bytes=max(peak_bytes,directory_bytes(root))
                except FileNotFoundError: pass
                if time.monotonic()-started>=timeout: reason='stage timeout'
                elif peak>memory_bytes: reason='memory limit'
                elif peak_bytes>output_bytes: reason='output size limit'
                if reason:
                    if cancel_path is not None:
                        Path(cancel_path).parent.mkdir(parents=True,exist_ok=True)
                        Path(cancel_path).write_text(reason,encoding='utf-8')
                        # Linux owns its MPI ranks. Give its independent guard a
                        # chance to terminate/reap them before killing the launcher.
                        try: process.wait(timeout=5)
                        except subprocess.TimeoutExpired: pass
                    terminated=stop_tree(process); break
                time.sleep(.25)
        except BaseException:
            if not stop_tree(process): raise RuntimeError('Child termination could not be verified')
            raise
        if process.poll() is None or terminated is False:
            raise RuntimeError('Child termination could not be verified')
        code=process.wait()
    return dict(command=command,returncode=code,elapsed_s=time.monotonic()-started,
        peak_rss_bytes=peak,peak_output_bytes=peak_bytes,reason=reason,
        termination_verified=terminated if reason else True)
