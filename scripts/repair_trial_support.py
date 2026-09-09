"""OS commit cap for the supplemental Boolean trial; no global system settings."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
from runflow import shape_resources as resources
from runflow.shape_audit import file_sha
from runflow.shape_fullbody import read


class HardCommitJob(resources.OwnedJob):
    def __init__(self,limit):
        super().__init__()
        class Basic(ctypes.Structure):
            _fields_=[('ProcessTime',ctypes.c_longlong),('JobTime',ctypes.c_longlong),('Flags',wintypes.DWORD),
                ('MinWorkingSet',ctypes.c_size_t),('MaxWorkingSet',ctypes.c_size_t),('ActiveLimit',wintypes.DWORD),
                ('Affinity',ctypes.c_size_t),('Priority',wintypes.DWORD),('Scheduling',wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_=[('Basic',Basic),('Io',ctypes.c_ulonglong*6),('ProcessMemory',ctypes.c_size_t),
                ('JobMemory',ctypes.c_size_t),('PeakProcessMemory',ctypes.c_size_t),('PeakJobMemory',ctypes.c_size_t)]
        info=Extended(); info.Basic.Flags=0x2000|0x200  # KILL_ON_JOB_CLOSE | JOB_MEMORY
        info.JobMemory=int(limit)
        if not self.api.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            self.close(); raise ctypes.WinError(ctypes.get_last_error())


def guarded(*args,**kwargs):
    original=resources.OwnedJob
    resources.OwnedJob=lambda:HardCommitJob(kwargs['limits']['private_commit_bytes'])
    try:
        result=resources.run(*args,**kwargs)
        result['os_enforced_job_commit_limit_bytes']=kwargs['limits']['private_commit_bytes']
        return result
    finally: resources.OwnedJob=original


_dll_handles=[]
def manifold_backend(repo):
    root=Path(repo)/'.tools/manifold3d-3.5.2'; manifest=read(root/'install.json')
    if manifest['version']!='3.5.2' or manifest['wheel_sha256']!='a129d7a09421dd5e246503006c0f39f7dc73933b4ba80f4eae5e267805aac72f':
        raise ValueError('Wrong Manifold wheel pin')
    for relative,sha in manifest['files'].items():
        path=(root/relative).resolve()
        if not path.is_relative_to(root.resolve()) or file_sha(path)!=sha: raise ValueError('Manifold binary hash mismatch')
    if os.name=='nt': _dll_handles.append(os.add_dll_directory(str(root/'manifold3d-3.5.2.data/platlib')))
    sys.path.insert(0,str(root))
    import manifold3d
    return manifold3d
