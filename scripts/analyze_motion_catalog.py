"""Build a private shortlist; never promotes filename evidence to canonical motion."""
import argparse
import csv
from collections import Counter
from pathlib import Path
import re
import sqlite3
from runflow.core import file_hash, read, write
from runflow.motions import classify


def main():
    p=argparse.ArgumentParser();p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--game-data",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    private=Path(__file__).resolve().parents[1]/"private"
    if not a.output.resolve().is_relative_to(private.resolve()):raise ValueError("Private output required")
    if a.output.exists():raise ValueError("Fresh output required")
    catalog=read(a.catalog)
    if file_hash(a.game_data/"meta")!=catalog["meta_sha256"]:raise ValueError("Catalog and installed game differ")
    raw=[r for r in catalog["records"] if r["path"].startswith("3d/motion/racemain/")
         or re.search(r"(?:chara/chr|card/body/crd)1006(?:_|/|$)",r["path"])]
    rows=classify(raw)
    for row in rows:
        locator=row["asset_hash"]
        # JP locators include base32-like strings; they are not content SHA-256s.
        if not locator or not re.fullmatch(r"[A-Za-z0-9]{32,64}",locator):raise ValueError("Invalid asset locator")
        path=a.game_data/"dat"/locator[:2]/locator
        row["local_file_present"]=path.is_file()
        row["local_file_sha256"]=file_hash(path) if path.is_file() else None
    master=a.game_data/"master/master.mdb"
    before=file_hash(master)
    with sqlite3.connect(master.resolve().as_uri()+"?mode=ro",uri=True) as db:
        running_type=db.execute("SELECT race_running_type FROM chara_data WHERE id=1006").fetchone()[0]
    if before!=file_hash(master):raise ValueError("Master changed during read")
    summary={"schema_version":"1","meta_sha256":catalog["meta_sha256"],"master_sha256":before,
        "catalog_file_sha256":file_hash(a.catalog),"all_motion_count":len(catalog["records"]),
        "shortlist_count":len(rows),"racemain_count":sum(r["source_path"].startswith("3d/motion/racemain/") for r in rows),
        "character_id":"1006","race_running_type":running_type,"type_mapping_verified":False,
        "canonical_motion_id":None,"scientific_status":"PENDING_HUMAN_REVIEW",
        "root_counts":dict(sorted(Counter(r["path"].split("/")[2] for r in catalog["records"]).items()))}
    a.output.mkdir(parents=True)
    write(a.output/"shortlist.json",rows);write(a.output/"summary.json",summary)
    fields=["source_path","asset_hash","local_file_present","local_file_sha256","ui_generic_eligible","target","body_motion_candidate","verified"]
    with (a.output/"MOTION_MAP.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");writer.writeheader();writer.writerows(rows)
    print("SHORTLIST",len(rows),"RACE",summary["racemain_count"],"OGURI_RUNNING_TYPE",running_type,"CANONICAL_UNVERIFIED")


if __name__=="__main__":main()
