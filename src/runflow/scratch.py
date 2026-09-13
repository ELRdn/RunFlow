"""A4: scratch staging, checksummed copy-back, and preflight.

Authoritative artifacts live in the archive.  Scratch holds the working copy
of Python/Blender/audit stages plus, optionally, the Linux-native OpenFOAM
case tree.  Only canonical artifacts are copied back; the reproducible case
tree and the projection cache stay in scratch.

Nothing here deletes an archived artifact.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from .cfd_paths import is_private, reserve_reason, scratch_win, scratch_wsl
from .core import read, write

MANIFEST_SCHEMA = "phase1-scratch-copyback-1"

# Trees that stay in scratch: reproducible from the archived inputs, or the
# high-churn OpenFOAM case that already lives on the Linux scratch.
SCRATCH_ONLY_TREES = ("case", "tool-sources", "projection-cache", "prior-projection-output")


def file_sha(path):
    path = Path(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def preflight(root):
    """Return a refusal reason when the target cannot be used safely."""
    reason = reserve_reason(root)
    if reason:
        return reason
    path = Path(root)
    parent = path if path.exists() else path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.exists():
        return "scratch parent is missing"
    free = shutil.disk_usage(parent).free
    if free < 20 * 1024 ** 3:
        return "scratch free space below 20 GiB"
    return None


def scratch_parent(name, root=None):
    """Scratch campaign root for one named campaign."""
    base = Path(root) if root is not None else scratch_win()
    return base / name


def linux_case_root(campaign_name, label, root=None):
    """POSIX path of the Linux-native case tree for one frame (WSL only)."""
    base = str(root) if root is not None else str(scratch_wsl())
    return base.rstrip("/") + "/" + campaign_name + "/" + label


def copy_back_frame(scratch_frame, archive_frame, *, manifest_name="archive-manifest.json"):
    """Copy canonical artifacts back, atomically, and record their checksums."""
    scratch_frame = Path(scratch_frame)
    archive_frame = Path(archive_frame)
    if not scratch_frame.is_dir():
        raise ValueError("Scratch frame is missing: " + str(scratch_frame))
    archive_frame.mkdir(parents=True, exist_ok=True)
    copied = {}
    skipped = []
    for path in sorted(scratch_frame.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(scratch_frame)
        if relative.parts and relative.parts[0] in SCRATCH_ONLY_TREES:
            skipped.append(relative.as_posix())
            continue
        target = archive_frame / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        shutil.copyfile(path, temp)
        temp.replace(target)
        copied[relative.as_posix()] = file_sha(target)
    manifest = dict(schema_version=MANIFEST_SCHEMA, frame=str(archive_frame.name),
                    source=str(scratch_frame), files=copied,
                    scratch_only=sorted(skipped), authoritative=True)
    write(archive_frame / manifest_name, manifest)
    return manifest


def verify_manifest(archive_frame, manifest_name="archive-manifest.json"):
    """Re-verify a copy-back manifest against the archive bytes."""
    archive_frame = Path(archive_frame)
    manifest = read(archive_frame / manifest_name)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("Wrong copy-back manifest schema")
    for relative, expected in manifest.get("files", {}).items():
        path = archive_frame / relative
        if not path.is_file() or file_sha(path) != expected:
            raise ValueError("Archived artifact changed: " + relative)
    return manifest


def job_commit_limit(total_bytes, workers):
    """Split a total commit budget across isolated workers."""
    workers = int(workers)
    if workers < 1:
        raise ValueError("Worker count must be positive")
    total = int(total_bytes)
    if total < workers:
        raise ValueError("Commit budget is smaller than the worker count")
    return total // workers
