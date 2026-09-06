"""Read-only, narrow game intake. Never exports or edits game databases."""
import argparse
import sqlite3
from pathlib import Path
from runflow.core import file_hash, write


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--game-data",type=Path,required=True)
    p.add_argument("--steam-build",required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    master=a.game_data/"master/master.mdb"
    for path in [a.game_data/"meta",master,a.game_data/"dat"]:
        if not path.exists(): raise SystemExit("Missing game data component: "+path.name)
    before=master.stat()
    with sqlite3.connect(master.resolve().as_uri()+"?mode=ro",uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        name=c.execute('SELECT text FROM text_data WHERE category=6 AND "index"=1006').fetchone()
        dress=c.execute('SELECT text FROM text_data WHERE category=14 AND "index"=100602').fetchone()
        relation=c.execute('SELECT chara_id,use_race,head_sub_id FROM dress_data WHERE id=100602').fetchone()
    if name != ("オグリキャップ",) or dress != ("シンデレラグレイ",) or not relation or relation[:2] != (1006,1):
        raise SystemExit("Requested character/costume identity mismatch; no substitution")
    master_hash=file_hash(master)
    after=master.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise SystemExit("Database changed during intake; retry after game update finishes")
    report={"schema_version":"1","region":"JP","platform":"Steam","steam_build":a.steam_build,
            "master_sha256":master_hash,"meta_sha256":file_hash(a.game_data/"meta"),
            "character_id":"1006","character_name":name[0],"costume_id":"100602","costume_name":dress[0],
            "head_sub_id":relation[2],"motion_id":None,"model_import_status":"NOT_VERIFIED",
            "notes":["Local master identity only; asset bundles, motion and geometry not validated",
                     "chara_data.height is a category, not physical height; do not use it as metres"]}
    write(a.output,report)
    print("IDENTITY_PASS; IMPORT_NOT_VERIFIED")


if __name__=="__main__": main()
