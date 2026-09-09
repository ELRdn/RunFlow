"""Explicit private roots and reserve checks shared by Windows and WSL."""
import os
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[2]


def private_roots():
    external = Path('E:/RunFlowPrivate/phase1') if os.name == 'nt' else Path('/mnt/e/RunFlowPrivate/phase1')
    return (REPO / 'private', external)


def is_private(path, repo=None):
    path = Path(path).resolve()
    roots = private_roots() if repo is None else (Path(repo)/'private', private_roots()[1])
    return any(path.is_relative_to(root.resolve()) for root in roots)


def reserve_reason(root):
    root = Path(root).resolve()
    if not root.is_relative_to(private_roots()[1].resolve()):
        return None
    for drive, gib in [('E', 50), ('C', 20), ('D', 15)]:
        path = Path(drive + ':/') if os.name == 'nt' else Path('/mnt/' + drive.lower())
        if not path.exists() or shutil.disk_usage(path).free < gib * 1024**3:
            return 'disk reserve ' + drive
    return None
