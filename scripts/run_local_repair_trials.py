"""Explicit finite selection; existing labels and failed runs are never retried."""
import argparse
from pathlib import Path
from run_local_surface_repair import run

TRIALS={
 'carve-m005-multiv2':('carve',['--margin','.05','--angles=-35,0,35','--regions','face-visible,hair-visible,hair-gap']),
 'carve-m005-multi':('carve',['--margin','.05','--angles=-35,0,35','--regions','face-visible,hair-visible,hair-gap']),
 'carve-m005-fine':('carve',['--margin','.05','--step','.05']),
 'face-replace-r1':('replacement',['--region','face-visible','--rings','1']),
 'face-replace-r2':('replacement',['--region','face-visible','--rings','2']),
 'hair-replace-r1':('replacement',['--region','hair-visible','--rings','1']),
 'hair-replace-r2':('replacement',['--region','hair-visible','--rings','2']),
 'face-thin040':('thin',['--region','face-visible','--thickness','.4']),
 'hair-thin040':('thin',['--region','hair-visible','--thickness','.4']),
 'face-thin020':('thin',['--region','face-visible','--thickness','.2']),
 'face-thin010':('thin',['--region','face-visible','--thickness','.1']),
 'face-fit-nearest1':('fit',['--region','face-visible','--mode','nearest','--steps','1']),
 'face-fit-normal1':('fit',['--region','face-visible','--mode','normal','--steps','1']),
 'face-fit-axis1':('fit',['--region','face-visible','--mode','axis','--steps','1']),
 'face-fit-nearest5':('fit',['--region','face-visible','--mode','nearest','--steps','5']),
 'hair-fit-nearest1':('fit',['--region','hair-visible','--mode','nearest','--steps','1']),
 'reference1000-carve':('carve',['--base','reference1000','--margin','.05']),
}


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--trial',choices=TRIALS,action='append',required=True);a=p.parse_args()
    for label in a.trial:
        if (a.root/'runs'/label).exists():raise ValueError('Existing trial; automatic retry is prohibited: '+label)
    for label in a.trial:
        task,options=TRIALS[label];result=run(a.root,'repair',task,label,options,900)
        if not result['complete']:raise SystemExit(2)


if __name__=='__main__':main()
