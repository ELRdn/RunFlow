"""Measured local projections and private resolution-study figures."""
import argparse
import json
from pathlib import Path
import sys
import time
import shutil
import numpy as np
import shapely
from shapely.plotting import plot_polygon
from runflow.shape_audit import file_sha,load_surface,SAMPLE_DTYPE
from runflow.shape_projection import project_mesh,compare_projections
from runflow.cfd_guard import run
from runflow.core import digest

REPO=Path(__file__).resolve().parents[1]


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def write(path,value): path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def cases(request):
    return ['global']+[f'h{round(h*1000)}-v{round(v*1e6)}' for h in request['halos_m'] for v in request['voxel_sizes_m']]


def projection(root,roi,case):
    base=root/roi['id']; folder=base/case
    source=base/'source-core' if case=='source' else base/'global-core' if case=='global' else folder/'core'
    v,f=load_surface(source)
    value=shapely.set_precision(project_mesh(v,f,axes=roi['axes'],grid_size=1e-9),1e-9)
    if not value.is_valid: raise ValueError('Invalid local projection')
    if case=='source':
        (base/'source.wkb').write_bytes(shapely.to_wkb(value)); return
    original=shapely.from_wkb((base/'source.wkb').read_bytes())
    (folder/'projection.wkb').write_bytes(shapely.to_wkb(value))
    metrics=compare_projections(original,value)
    metrics['precision_grid_m']=1e-9
    if 'gap_wkb' in roi:
        gap=shapely.from_wkb(Path(roi['gap_wkb']).read_bytes())
        filled=gap.intersection(value).area
        metrics['original_gap']=dict(area_mm2=gap.area*1e6,filled_mm2=filled*1e6,filled_fraction=filled/gap.area)
    write(folder/'projection.json',metrics)
    print('LOCAL_PROJECTION_DONE',roi['id'],case,metrics['relative_change'],flush=True)


def compare_distances(first,second):
    a=np.memmap(first,dtype=SAMPLE_DTYPE,mode='r'); b=np.memmap(second,dtype=SAMPLE_DTYPE,mode='r')
    if len(a)!=len(b) or not np.array_equal(a['point'],b['point']) or not np.array_equal(a['area'],b['area']):
        raise ValueError('Source-core sample mismatch')
    d=np.abs(a['distance'].astype(float)-b['distance'].astype(float)); w=a['area'].astype(float)
    return dict(sampled_max_delta_m=float(d.max()),area_weighted_mean_delta_m=float(np.dot(d,w)/w.sum()),
        fraction_above_025mm=float(w[d>.00025].sum()/w.sum()),
        note='Difference of distances from the same original points, not a Hausdorff distance between candidates')


def summarize(root,request):
    results={}; missing=[]
    for roi in request['regions']:
        base=root/roi['id']; entries={}
        for case in cases(request):
            p=base/case/'projection.json'; m=base/case/'measurement.json'
            execution_names=[roi['id']+'-'+case+'-measure',roi['id']+'-'+case+'-projection']
            if case!='global': execution_names.append(roi['id']+'-'+case+'-remesh')
            executions=[root/(name+'.execution.json') for name in execution_names]
            execution_ok=all(p.exists() and read(p)['returncode']==0 and not read(p)['reason'] for p in executions)
            if not execution_ok or not p.exists() or not m.exists() or not read(m).get('complete'):
                missing.append(roi['id']+'/'+case); continue
            value=dict(projection=read(p),measurement=read(m))
            if (base/case/'remesh.json').exists(): value['remesh']=read(base/case/'remesh.json')
            entries[case]=value
        comparisons={}
        pairs=[('global-context', 'global', f'h{round(request["halos_m"][-1]*1000)}-v1000')]
        pairs += [(str(round(v*1e6)),f'h{round(request["halos_m"][0]*1000)}-v{round(v*1e6)}',
                   f'h{round(request["halos_m"][1]*1000)}-v{round(v*1e6)}') for v in request['voxel_sizes_m']]
        for label,a,b in pairs:
            if a not in entries or b not in entries: continue
            value=compare_distances(base/a/'forward.samples',base/b/'forward.samples')
            ga=shapely.from_wkb((base/a/'projection.wkb').read_bytes()); gb=shapely.from_wkb((base/b/'projection.wkb').read_bytes())
            source_area=entries[a]['projection']['source_m2']
            value['projection_symmetric_difference_relative']=ga.symmetric_difference(gb).area/source_area
            value['within_screening_limits']=(value['sampled_max_delta_m']<=.00025 and value['projection_symmetric_difference_relative']<=.005)
            comparisons[label]=value
        results[roi['id']]=dict(cases=entries,context_comparisons=comparisons)
    identity=dict(input_sha256={k:v['sha256'] for k,v in request['inputs'].items()},
        regions=[{k:v for k,v in r.items() if k!='gap_wkb'} for r in request['regions']],
        gap_reference_sha256={r['id']:file_sha(r['gap_wkb']) for r in request['regions'] if 'gap_wkb' in r},
        voxel_sizes_m=request['voxel_sizes_m'],halos_m=request['halos_m'],cover_m=request['cover_m'],
        tool_pins=read(root/'tool-pins.json'),report_tool_pins=read(root/'report-tool-pins.json'),
        render_tool_pins=read(root/'render-tool-pins.json') if (root/'render-tool-pins.json').exists() else None)
    result=dict(study_id='rf-local-'+digest(identity),identity=identity,results=results,missing=missing,
        comparison_complete=not missing,scientific_status='LOCAL_DIAGNOSTIC_ONLY',human_adoption=None,
        cfd_admission='UNCHANGED_BLOCKED',whole_body_replacement=False,ranking_eligible=False,
        context_screening=dict(sampled_distance_delta_m=.00025,projected_symmetric_difference_relative=.005,
            meaning='Sensitivity warning thresholds for this local experiment; no geometry tolerance or CFD gate changes'),
        note='Every resolution starts from original cleaned triangles; no caps/thickness or stitching. Two halos test limited context sensitivity; agreement is not proof against every crop effect.')
    write(root/'study-summary.json',result); return result


def draw(ax,g,color,alpha=1.):
    if g.is_empty: return
    if g.geom_type=='Polygon': plot_polygon(g,ax=ax,add_points=False,color=color,alpha=alpha,linewidth=.25)
    elif hasattr(g,'geoms'):
        for item in g.geoms: draw(ax,item,color,alpha)


def figures(root,request,summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    halo=round(request['halos_m'][-1]*1000)
    columns=['global']+[f'h{halo}-v{round(v*1e6)}' for v in request['voxel_sizes_m']]
    fig,axes=plt.subplots(len(request['regions']),len(columns),figsize=(18,11),layout='constrained')
    for row,roi in enumerate(request['regions']):
        base=root/roi['id']; source=shapely.from_wkb((base/'source.wkb').read_bytes())
        for col,case in enumerate(columns):
            ax=axes[row,col]; item=summary['results'][roi['id']]['cases'].get(case)
            if item is None: ax.set_title(case+' unavailable'); continue
            candidate=shapely.from_wkb((base/case/'projection.wkb').read_bytes())
            draw(ax,source.union(candidate),'#bdc9d0'); draw(ax,source.difference(candidate),'#c93657'); draw(ax,candidate.difference(source),'#d79529')
            title='Saved global 1mm' if case=='global' else f'Local {int(case.split("v")[1])/1000:g}mm'
            if 'original_gap' in item['projection']: detail=f'Gap filled: {item["projection"]["original_gap"]["filled_fraction"]*100:.2f}%'
            else: detail=f'Witness distance: {item["measurement"]["witness"]["distance_m"]*1000:.3f}mm'
            ax.set_title(title+'\n'+detail,fontsize=10)
            a,b=roi['axes']; ax.set_xlim(roi['low_m'][a],roi['high_m'][a]); ax.set_ylim(roi['low_m'][b],roi['high_m'][b]); ax.set_aspect('equal')
            ax.ticklabel_format(useOffset=False); ax.set_xlabel('XYZ'[a]+' [m]'); ax.set_ylabel(roi['id']+'\n'+'XYZ'[b]+' [m]')
    fig.suptitle(f'Local resolution study | red: original surface lost in projection; amber: new coverage | {halo}mm context\nLocal/global context differs: candidates are not accepted repairs')
    out=root/'figures'; out.mkdir(exist_ok=True); fig.savefig(out/'comparison.png',dpi=170); plt.close(fig)
    fig,axes=plt.subplots(2,len(request['regions']),figsize=(14,8.8),layout='constrained')
    for col,roi in enumerate(request['regions']):
        ax=axes[0,col]; coverage_ax=axes[1,col]
        values=summary['results'][roi['id']]['cases']
        for halo_m in request['halos_m']:
            x=[]; y=[]; coverage=[]
            for voxel in request['voxel_sizes_m']:
                case=f'h{round(halo_m*1000)}-v{round(voxel*1e6)}'
                if case not in values: continue
                item=values[case]; x.append(voxel*1000)
                y.append(item['projection']['original_gap']['filled_fraction']*100 if 'gap_wkb' in roi else item['measurement']['witness']['distance_m']*1000)
                coverage.append(item['projection']['intersection_m2']/item['projection']['source_m2']*100)
            ax.plot(x,y,'o-',label=f'{halo_m*1000:g}mm context')
            coverage_ax.plot(x,coverage,'o-',label=f'{halo_m*1000:g}mm context')
        for plot in (ax,coverage_ax):
            plot.set_xscale('log'); plot.invert_xaxis(); plot.set_xticks([1,.5,.25,.1],['1','.5','.25','.1'])
            plot.set_xlabel('Voxel size [mm]'); plot.legend(); plot.grid(alpha=.2)
        ax.set_ylabel('Original gap filled [%]' if 'gap_wkb' in roi else 'Selected original point distance [mm]')
        ax.set_title(roi['id']); coverage_ax.set_ylabel('Original projected area retained [%]'); coverage_ax.set_ylim(0,105)
    fig.suptitle('Distance or gap improvement alone is insufficient: local surface coverage is lost')
    fig.savefig(out/'resolution-trend.png',dpi=180); plt.close(fig)


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--region'); p.add_argument('--case'); p.add_argument('--report-only',action='store_true')
    args=p.parse_args(); root=args.root.resolve(); request=read(root/'request.json')
    if not root.is_relative_to(REPO/'private'): raise ValueError('Private study required')
    if args.case:
        roi=next(r for r in request['regions'] if r['id']==args.region); projection(root,roi,args.case); return
    if not args.report_only:
        pins={'runtime':file_sha(sys.executable)}
        for name in ('scripts/local_voxel_report.py','src/runflow/shape_audit.py','src/runflow/shape_projection.py','src/runflow/core.py','src/runflow/cfd_guard.py','uv.lock'):
            target=root/'report-tool-sources'/name; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(REPO/name,target); pins[name]=file_sha(target)
        write(root/'report-tool-pins.json',pins)
        deadline=time.monotonic()+request['projection_total_s']
        for roi in request['regions']:
            for case in ['source']+cases(request):
                label=roi['id']+'-'+case+'-projection'; record_path=root/(label+'.execution.json')
                if record_path.exists(): raise ValueError('Projection stage already attempted')
                if deadline<=time.monotonic(): break
                folder=root/roi['id']/case
                if case not in ('source','global') and not (folder/'remesh.json').exists(): continue
                cmd=[sys.executable,str(Path(__file__).resolve()),'--root',str(root),'--region',roi['id'],'--case',case]
                print('LOCAL_PROJECTION_START',label,flush=True)
                record=run(cmd,root=root,log=root/(label+'.log'),timeout=min(request['projection_timeout_s'],deadline-time.monotonic()),
                    memory_bytes=request['memory_bytes'],output_bytes=request['output_bytes'],cwd=REPO)
                write(record_path,record); print('LOCAL_PROJECTION_END',label,record['returncode'],round(record['elapsed_s'],2),flush=True)
                if record['reason']=='output size limit' or not record['termination_verified']: raise RuntimeError('Resource or termination failure')
                if case=='source' and record['returncode']!=0: break
    for item in request['inputs'].values():
        if file_sha(item['path'])!=item['sha256']: raise ValueError('Original input changed')
    if args.report_only:
        pins={}
        for name in ('scripts/local_voxel_report.py','src/runflow/shape_audit.py','src/runflow/shape_projection.py','src/runflow/core.py','uv.lock'):
            target=root/'render-tool-sources'/name; target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and file_sha(target)!=file_sha(REPO/name): raise ValueError('Render revision already pinned')
            if not target.exists(): shutil.copyfile(REPO/name,target)
            pins[name]=file_sha(target)
        write(root/'render-tool-pins.json',pins)
    summary=summarize(root,request); figures(root,request,summary)
    print('LOCAL_STUDY_REPORT',summary['study_id'],'complete',summary['comparison_complete'],flush=True)


if __name__=='__main__': main()
