"""Explicit private roots, scratch roots, and reserve checks (Windows and WSL).

Phase A adds two non-authoritative scratch slots, both on the NVMe D: drive:

* scratch_win() - Windows-native NTFS, used by Python and Blender stages.
* scratch_wsl() - Linux-native ext4 at /scratch, used by the high-churn
  OpenFOAM case tree.

E: remains the authoritative archive.  Scratch is never authoritative and is
never accepted in place of an archived artifact.
"""
import os
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[2]

PHASE_A_NAME = 'phase-a'
SCRATCH_WIN_NAME = 'RunFlowScratch'
SCRATCH_MIN_FREE_GIB = 20


def _windows():
    return os.name == 'nt'


def archive_roots():
    """Authoritative private roots: repository-private plus the E: archive."""
    external = Path('E:/RunFlowPrivate/phase1') if _windows() else Path('/mnt/e/RunFlowPrivate/phase1')
    return (REPO / 'private', external)


def scratch_roots():
    """Non-authoritative working roots, both on the NVMe D: drive."""
    windows = Path('D:/' + SCRATCH_WIN_NAME) if _windows() else Path('/mnt/d/' + SCRATCH_WIN_NAME)
    return (windows, Path('/scratch'))


def scratch_win():
    return scratch_roots()[0]


def scratch_wsl():
    return scratch_roots()[1]


def phase_a_root():
    """Private Phase A evidence root; never inside the Phase 1 archive tree."""
    base = 'E:/RunFlowPrivate/' if _windows() else '/mnt/e/RunFlowPrivate/'
    return Path(base + PHASE_A_NAME)


def private_roots():
    """Backward-compatible authoritative pair (repository-private, E: archive)."""
    return archive_roots()


def is_private(path, repo=None):
    """True for authoritative private roots, scratch slots, and Phase A evidence."""
    path = Path(path).resolve()
    roots = list(private_roots() if repo is None else (Path(repo) / 'private', private_roots()[1]))
    roots.extend(scratch_roots())
    roots.append(phase_a_root())
    return any(path.is_relative_to(root.resolve()) for root in roots)


def reserve_reason(root):
    """Refuse to start when a filesystem reserve required by the lane is missing."""
    root = Path(root).resolve()
    if any(root.is_relative_to(item.resolve()) for item in scratch_roots()):
        drive = Path('D:/') if _windows() else Path('/mnt/d')
        if not drive.exists() or shutil.disk_usage(drive).free < SCRATCH_MIN_FREE_GIB * 1024**3:
            return 'disk reserve D'
        return None
    if not root.is_relative_to(private_roots()[1].resolve()):
        return None
    for drive, gib in [('E', 50), ('C', 20), ('D', 15)]:
        path = Path(drive + ':/') if _windows() else Path('/mnt/' + drive.lower())
        if not path.exists() or shutil.disk_usage(path).free < gib * 1024**3:
            return 'disk reserve ' + drive
    return None
