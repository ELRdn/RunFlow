"""Read only motion names/hashes from local meta; never dump keys or a decrypted DB.

Encrypted JP meta uses the pinned UmaViewer sqlite3mc library and its existing
local configuration. No credentials or key bytes are emitted in files or errors.
"""
import argparse
import ctypes as c
import json
from pathlib import Path
import sqlite3

from runflow.core import file_hash, write

SQL = "SELECT n,h,d,m FROM a WHERE n LIKE '3d/motion/%' ORDER BY n"


def plain_rows(meta):
    with sqlite3.connect(meta.resolve().as_uri()+"?mode=ro", uri=True) as db:
        return list(db.execute(SQL))


def encrypted_rows(meta, viewer):
    dll_path = viewer / "UmaViewer_Data/Plugins/x86_64/sqlite3mc_x64.dll"
    if not dll_path.is_file():
        raise ValueError("Pinned sqlite3mc library missing")
    config = json.loads((viewer/"Config.json").read_text(encoding="utf-8-sig"))
    seed, mask = bytes.fromhex(config["DBKeyText"]), bytes.fromhex(config["DBBaseKeyText"])
    if len(mask)<13 or not seed:
        raise ValueError("Local viewer key configuration is incomplete")
    key = bytes(v ^ mask[i%13] for i,v in enumerate(seed))
    lib = c.CDLL(str(dll_path.resolve()))
    def bind(name, args, result=c.c_int):
        fn=getattr(lib,name);fn.argtypes=args;fn.restype=result;return fn
    open_db=bind("sqlite3_open_v2",[c.c_char_p,c.POINTER(c.c_void_p),c.c_int,c.c_void_p])
    close=bind("sqlite3_close",[c.c_void_p])
    configure=bind("sqlite3mc_config",[c.c_void_p,c.c_char_p,c.c_int])
    set_key=bind("sqlite3_key",[c.c_void_p,c.c_void_p,c.c_int])
    prepare=bind("sqlite3_prepare_v2",[c.c_void_p,c.c_char_p,c.c_int,c.POINTER(c.c_void_p),c.c_void_p])
    step=bind("sqlite3_step",[c.c_void_p])
    column=bind("sqlite3_column_text",[c.c_void_p,c.c_int],c.c_char_p)
    finalize=bind("sqlite3_finalize",[c.c_void_p])
    db, stmt=c.c_void_p(),c.c_void_p()
    try:
        if open_db(str(meta.resolve()).encode("utf-8"),c.byref(db),1,None)!=0:
            raise ValueError("Read-only meta open failed")
        configure(db,b"cipher",3)
        key_buffer=c.create_string_buffer(key)
        if set_key(db,key_buffer,len(key))!=0:
            raise ValueError("Local meta configuration rejected")
        if prepare(db,SQL.encode(),-1,c.byref(stmt),None)!=0:
            raise ValueError("Motion query failed; verify pinned viewer and JP data")
        rows=[]
        while True:
            rc=step(stmt)
            if rc==101:break
            if rc!=100:raise ValueError("Motion query did not finish")
            rows.append(tuple((column(stmt,i) or b"").decode("utf-8") for i in range(4)))
        return rows,dll_path
    finally:
        if stmt:finalize(stmt)
        if db:close(db)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--game-data",type=Path,required=True)
    p.add_argument("--viewer",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    project=Path(__file__).resolve().parents[1]
    output=a.output.resolve()
    if not output.is_relative_to((project/"private").resolve()):
        raise ValueError("Motion catalogs must remain under project/private")
    if output.exists():raise ValueError("Use a fresh output directory")
    meta=a.game_data/"meta"
    before=file_hash(meta)
    with meta.open("rb") as f:plain=f.read(16)==b"SQLite format 3\x00"
    dll=None
    if plain:rows=plain_rows(meta)
    else:rows,dll=encrypted_rows(meta,a.viewer)
    if file_hash(meta)!=before:raise ValueError("Meta changed during catalog read; retry")
    records=[{"path":n,"asset_hash":h,"prerequisites":d,"asset_type":m} for n,h,d,m in rows]
    if not records:raise ValueError("No motion entries found")
    output.mkdir(parents=True)
    write(output/"catalog.json",{"schema_version":"1","meta_sha256":before,
        "umaviewer_commit":"d50b28379337b507751a7df705a10afeab2c37ce",
        "reader":"sqlite3 readonly" if plain else "sqlite3mc readonly/cipher3",
        "sqlite3mc_sha256":file_hash(dll) if dll else None,
        "records":records,"canonical_verified":False})
    (output/"motions.txt").write_text("\n".join(r["path"] for r in records)+"\n",encoding="utf-8")
    print("READONLY_MOTION_CATALOG",len(records),"entries; source unchanged")


if __name__=="__main__":
    try:main()
    except (ValueError,OSError,KeyError,sqlite3.Error) as error:
        # Do not emit config values or native diagnostics which may include keys.
        raise SystemExit("BLOCKED: motion catalog extraction failed ("+type(error).__name__+")") from None
