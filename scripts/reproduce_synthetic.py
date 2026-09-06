"""Original synthetic fixtures prove infrastructure, never official asset fidelity."""
import argparse
import hashlib
from pathlib import Path
from runflow.core import write, generate, canonical


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=False)
    from runflow.core import read
    root=Path(__file__).resolve().parents[1]
    m=read(root/"configs/manifest.pilot.template.json")
    m["source"]["game_version"]="SYNTHETIC_NOT_GAME_DATA"
    m["source"]["motion_id"]="synthetic-one-second"
    m.update(height_m=1.6,height_source="Synthetic fixture",height_measurement="Original 1.6m reference")
    m["transform"].update(source_to_rf=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
                          meters_per_source_unit=1,reflection=False,scale_evidence="Synthetic metre geometry")
    m["gait"].update(start_s=1,end_s=2,contact_event="synthetic left contact",recording_step_s=1/60,warmup_steps=60)
    for role in ["model","motion"]:
        data=("RUNFLOW_SYNTHETIC_"+role).encode()
        (a.output/(role+".bin")).write_bytes(data)
        m["assets"].append({"id":"synthetic-"+role,"role":role,"path":role+".bin","sha256":hashlib.sha256(data).hexdigest()})
    write(a.output/"manifest.json",m)
    first,result=generate(m,a.output); second,_=generate(m,a.output)
    write(a.output/"experiment-1.json",first); write(a.output/"experiment-2.json",second)
    write(a.output/"result.json",result)
    if canonical(first)!=canonical(second):raise SystemExit("Reproduction failed")
    write(a.output/"reproduction.json",{"synthetic_only":True,"identical":True,"config_sha256":first["config_sha256"]})
    print("SYNTHETIC_REPRODUCTION_PASS",first["config_sha256"])


if __name__=="__main__":main()
