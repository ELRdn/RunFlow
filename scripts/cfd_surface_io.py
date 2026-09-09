"""Linux-local diagnostic I/O. cfd_worker supervises this entire process tree.

Copying, hashing, the unchanged checker, archiving and cleanup share one deadline
and resource budget. The supervisor retains scratch after an interrupted job.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tarfile


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, sort_keys=True, allow_nan=False))
    temp.replace(path)


def check_local(source, root, scratch, checker='surfaceCheck'):
    source, root, scratch = (Path(p).resolve() for p in (source, root, scratch))
    if scratch.parent != Path(tempfile.gettempdir()).resolve() or not scratch.name.startswith('runflow-cfd-surface-'):
        raise ValueError('Unexpected owned scratch directory')
    if source == scratch / 'candidate.obj' or root.is_relative_to(scratch):
        raise ValueError('Private archive must be outside disposable scratch')
    if shutil.disk_usage(scratch).free < 20 * 1024**3:
        raise ValueError('Linux scratch disk reserve')
    original_hash = sha(source)
    copied = scratch / 'candidate.obj'
    shutil.copyfile(source, copied)
    if sha(copied) != original_hash:
        raise ValueError('Scratch input hash mismatch')
    checker_path = Path(shutil.which(checker) or checker).resolve(strict=True)
    record = dict(source_sha256=original_hash, copied_sha256=original_hash,
                  checker_sha256=sha(checker_path), complete=False, local_linux_io=True,
                  input_format='binary64 round-trip OBJ', diagnostics=None)
    save(root / 'surface-io.json', record)
    # Both the source parent and cwd matter: Foundation14 writes diagnostics to both.
    with (root / 'surfaceCheck.log').open('wb') as log:
        result = subprocess.run([str(checker_path), '-checkSelfIntersection', str(copied)],
                                cwd=scratch, stdout=log, stderr=subprocess.STDOUT)
    record['checker_returncode'] = result.returncode
    save(root / 'surface-io.json', record)
    archive = scratch / 'diagnostics.tar'
    with tarfile.open(archive, 'w') as output:
        for path in sorted(scratch.iterdir()):
            if path.name not in ('candidate.obj', 'diagnostics.tar'):
                output.add(path, arcname=path.name)
    archive_hash = sha(archive)
    destination = root / 'surface-diagnostics.tar'
    shutil.copyfile(archive, destination)
    if sha(destination) != archive_hash:
        raise ValueError('Diagnostic archive hash mismatch')
    record['diagnostics'] = dict(file=destination.name, sha256=archive_hash,
                                 bytes=destination.stat().st_size)
    # Delete only the verified, owned temporary directory after its child exited
    # and the complete diagnostic archive was verified in the private output.
    shutil.rmtree(scratch)
    record.update(complete=True, scratch_removed=True)
    save(root / 'surface-io.json', record)
    return result.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('source', 'root', 'scratch'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(check_local(args.source, args.root, args.scratch))
