"""Read-only package fingerprint with explicit audit timing, separate from recipe identity."""
import argparse
import importlib.metadata
from pathlib import Path
import sys
from datetime import datetime,timezone
import hashlib
import json
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();started=time.monotonic()
    site=Path(sys.prefix)/'Lib/site-packages';files={};mtimes={}
    for name in ('numpy','numpy.libs','shapely','shapely.libs'):
        for path in sorted((site/name).rglob('*')):
            if path.is_file() and path.suffix in ('.py','.pyd','.dll'):
                key=path.relative_to(site).as_posix()
                with path.open('rb') as stream:files[key]=hashlib.file_digest(stream,'sha256').hexdigest()
                mtimes[key]=path.stat().st_mtime_ns
    versions={n:importlib.metadata.version(n) for n in ('numpy','shapely','psutil','matplotlib')}
    identity=dict(versions=versions,files=files);digest=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    result=dict(**identity,fingerprint=digest,file_mtimes_ns=mtimes,audited_at=datetime.now(timezone.utc).isoformat(),
        elapsed_s=time.monotonic()-started,note='Observed at this timestamp; this audit is not a retroactive pre-run pin.')
    with a.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print('RUNTIME_FINGERPRINT',digest,result['elapsed_s'],flush=True)


if __name__=='__main__':main()
