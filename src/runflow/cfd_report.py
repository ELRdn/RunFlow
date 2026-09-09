"""Private, reproducible plots. Absent CFD fields are explicitly marked unavailable."""
import html
import math
import re
from pathlib import Path
import time

from .core import read,write


from .cfd_vtk import read_vtk


def internal_vtk_files(case):
    """Read each rank once; never include patch files or global link aliases."""
    case=Path(case)
    partitions=sorted(p for p in case.glob('processor[0-9]*') if re.fullmatch(r'processor\d+',p.name))
    folders=[p/'VTK' for p in partitions] if partitions else [case/'VTK']
    selected=[]
    for folder in folders:
        candidates=[]
        for path in folder.glob('*.vtk'):
            try: iteration=float(path.stem.rsplit('_',1)[1])
            except (ValueError,IndexError): continue
            if math.isfinite(iteration): candidates.append((iteration,path))
        if candidates:
            latest=max(t for t,_ in candidates)
            matches=[p for t,p in candidates if t==latest]
            if len(matches)!=1: raise ValueError('Ambiguous internal VTK files: '+str(folder))
            selected.extend(matches)
    return selected


def hull(points):
    points=sorted(set(points))
    def cross(o,a,b): return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower=[]; upper=[]
    for p in points:
        while len(lower)>1 and cross(lower[-2],lower[-1],p)<=0: lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper)>1 and cross(upper[-2],upper[-1],p)<=0: upper.pop()
        upper.append(p)
    return lower[:-1]+upper[:-1]


UNAVAILABLE = 'unavailable'

RSS_SCOPE = ('RSS scope: each Windows guarded value covers its process tree, each '
    'Linux worker value covers its Linux MPI descendant tree; the summary keeps maxima only '
    'and never sums nested durations.')

TAIL_BYTES = 65536
TAIL_LINES = 40
MAX_EXCERPTS = 10
SMALL_FILE_BYTES = 8192


def _read_json_or_none(path):
    try:
        return read(Path(path))
    except (OSError, ValueError):
        return None


def _number_or_none(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _tail_lines(path):
    try:
        with open(path, 'rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - TAIL_BYTES))
            text = stream.read().decode('utf-8', 'replace')
    except OSError:
        return None
    lines = text.splitlines()
    return lines[-TAIL_LINES:] if len(lines) > TAIL_LINES else lines


def _resource_entry(source, cmd):
    reason = cmd.get('reason')
    code = cmd.get('returncode')
    return dict(source=source,
        elapsed_s=_number_or_none(cmd.get('elapsed_s')),
        peak_rss_bytes=_number_or_none(cmd.get('peak_rss_bytes')),
        peak_output_bytes=_number_or_none(cmd.get('peak_output_bytes')),
        returncode=code if isinstance(code, int) and not isinstance(code, bool) else None,
        reason=reason if isinstance(reason, str) else None)


def _collect_resources(root):
    root = Path(root)
    resources = []
    for path in sorted(root.glob('*-worker.json')):
        worker = _read_json_or_none(path)
        if not isinstance(worker, dict):
            continue
        commands = worker.get('commands')
        if not isinstance(commands, list):
            continue
        for cmd in commands:
            if isinstance(cmd, dict):
                resources.append(_resource_entry(path.name, cmd))
    for path in sorted(root.glob('*.log.execution.json')):
        cmd = _read_json_or_none(path)
        if isinstance(cmd, dict):
            resources.append(_resource_entry(path.name, cmd))
    return resources


def _summarize_wall(root):
    state = _read_json_or_none(Path(root) / 'state.json')
    started = _number_or_none(state.get('started_epoch')) if isinstance(state, dict) else None
    updated = _number_or_none(state.get('updated_epoch')) if isinstance(state, dict) else None
    if started is None:
        return dict(status=UNAVAILABLE, source='state.json', started_epoch=None,
            updated_epoch=updated, total_elapsed_wall_s=None)
    end = _number_or_none(state.get('completed_epoch')) or time.time()
    total = end - started
    if not math.isfinite(total) or total < 0:
        return dict(status=UNAVAILABLE, source='state.json', started_epoch=started,
            updated_epoch=updated, total_elapsed_wall_s=None)
    return dict(status='available', source='state.json', started_epoch=started,
        updated_epoch=updated, total_elapsed_wall_s=total)


def _summarize_cells(root):
    evidence = _read_json_or_none(Path(root) / 'mesh-evidence.json')
    cells = _number_or_none(evidence.get('cells')) if isinstance(evidence, dict) else None
    if cells is None:
        return dict(status=UNAVAILABLE, source='mesh-evidence.json', cells=None)
    return dict(status='available', source='mesh-evidence.json', cells=cells)


def _layer_diagnostics(root):
    source = 'snappyHexMesh.log'
    lines = _tail_lines(Path(root) / source)
    if lines is None:
        return dict(status=UNAVAILABLE, source=source, excerpts=[])
    excerpts = [line.strip() for line in lines if 'layer' in line.lower() or line.lstrip().startswith('oguri')]
    rows=[]
    for line in lines:
        match=re.match(r'\s*(oguri\w*)\s+(\d+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*$',line)
        if match:
            rows.append(dict(patch=match[1],faces=int(match[2]),mean_layers=float(match[3]),
                mean_thickness_m=float(match[4]),desired_thickness_percent=float(match[5])))
    # Average layer count/thickness cannot establish the fraction of faces covered.
    rate=0 if rows and all(row['mean_layers']==0 for row in rows) else None
    return dict(status='available' if rows else UNAVAILABLE, source=source, excerpts=excerpts[:MAX_EXCERPTS],
        patches=rows,face_coverage_fraction=rate,coverage_status='available' if rate==0 else UNAVAILABLE)


def _yplus_diagnostics(root):
    source = 'case/postProcessing/yPlus'
    base = Path(root) / 'case' / 'postProcessing' / 'yPlus'
    try:
        files = sorted(p for p in base.rglob('*') if p.is_file())
    except OSError:
        files = []
    if not files:
        return dict(status=UNAVAILABLE, source=source, files=[], excerpts=[])
    names = [p.relative_to(base).as_posix() for p in files[:20]]
    excerpts = []
    for path in files[:MAX_EXCERPTS]:
        try:
            if path.stat().st_size > SMALL_FILE_BYTES:
                continue
            tail = path.read_text(encoding='utf-8', errors='replace').splitlines()[-TAIL_LINES:]
        except OSError:
            continue
        excerpts.append(dict(file=path.relative_to(base).as_posix(), lines=tail))
    return dict(status='available' if excerpts else UNAVAILABLE, source=source, files=names, excerpts=excerpts)


def _build_summary(root, resources):
    wall = _summarize_wall(root)
    cells = _summarize_cells(root)
    rss = [v for v in (_number_or_none(item.get('peak_rss_bytes')) for item in resources) if v is not None]
    out = [v for v in (_number_or_none(item.get('peak_output_bytes')) for item in resources) if v is not None]
    return dict(total_elapsed_wall_s=wall['total_elapsed_wall_s'], wall_status=wall['status'],
        wall_source=wall['source'], started_epoch=wall['started_epoch'], updated_epoch=wall['updated_epoch'],
        max_peak_rss_bytes=max(rss) if rss else None, max_peak_output_bytes=max(out) if out else None,
        rss_scope=RSS_SCOPE, cells=cells['cells'], cells_status=cells['status'], cells_source=cells['source'],
        layer=_layer_diagnostics(root), yplus=_yplus_diagnostics(root))


def create(root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    started=time.monotonic(); record=read(root/'result.json'); figures=[]; warnings=[]
    output=root/'report'; output.mkdir(exist_ok=True)
    if (root/'force-history.json').exists():
        rows=read(root/'force-history.json'); fig,ax=plt.subplots(figsize=(8,4))
        ax.plot([v['iteration'] for v in rows],[v['drag_N'] for v in rows]); ax.set(xlabel='Steady solver iteration',ylabel='Drag [N]',title='Provisional force history')
        ax.grid(True,alpha=.2); fig.tight_layout(); fig.savefig(output/'drag.png',dpi=160); plt.close(fig); figures.append('drag.png')
    if (root/'residual-history.json').exists():
        rows=read(root/'residual-history.json'); fig,ax=plt.subplots(figsize=(8,4))
        for field in ('p','Ux','Uy','Uz','k','omega'):
            data=sorted((float(t),v[field]) for t,v in rows.items() if field in v)
            if data: ax.semilogy([v[0] for v in data],[max(v[1],1e-16) for v in data],label=field)
        ax.set(xlabel='Steady solver iteration',ylabel='Initial residual',title='Residual histories'); ax.legend(); fig.tight_layout()
        fig.savefig(output/'residuals.png',dpi=160); plt.close(fig); figures.append('residuals.png')
    if not (root/'force-history.json').exists(): warnings.append('Force history unavailable: no exported force trace.')
    if not (root/'residual-history.json').exists(): warnings.append('Residual history unavailable: no exported residual trace.')
    vtk=internal_vtk_files(root/'case'); polygons=[]; pressure=[]; speed=[]
    if vtk:
        config=read(root/'experiment.json')['config']; center_y=sum(v[1] for v in config['source_bbox'])/2
        for file in vtk:
            if file.stat().st_size>256*1024**2:
                warnings.append('VTK file exceeds plotting limit; raw field retained: '+file.name); continue
            try: points,cells,fields=read_vtk(file)
            except ValueError as exc: warnings.append(str(exc)); continue
            for j,cell in enumerate(cells):
                vertices=[points[i] for i in cell]
                if min(v[1] for v in vertices)>center_y or max(v[1] for v in vertices)<center_y: continue
                cut=[]
                for i,a in enumerate(vertices):
                    for b in vertices[i+1:]:
                        if a[1]==b[1]: continue
                        t=(center_y-a[1])/(b[1]-a[1])
                        if 0<=t<=1: cut.append((a[0]+t*(b[0]-a[0]),a[2]+t*(b[2]-a[2])))
                polygon=hull(cut)
                if len(polygon)<3: continue
                polygons.append(polygon); pressure.append(fields['p'][j][0]*config['protocol']['air_density_kg_m3'])
                speed.append(math.sqrt(sum(x*x for x in fields['U'][j])))
        for name,values,label in [('mesh',None,'Mesh section'),('pressure',pressure,'Pressure [Pa]'),('speed',speed,'Speed [m/s]')]:
            if not polygons: break
            fig,ax=plt.subplots(figsize=(10,6))
            collection=PolyCollection(polygons,edgecolors='.35' if values is None else 'none',linewidths=.15,cmap='viridis')
            if values is None: collection.set_facecolor('white')
            else:
                import numpy as np
                collection.set_array(np.array(values)); fig.colorbar(collection,ax=ax,label=label)
            ax.add_collection(collection); ax.autoscale_view(); ax.set_aspect('equal')
            ax.set(xlabel='RF X [m]',ylabel='RF Z [m]',title=f'{label}, y={center_y:.4f} m; unvalidated smoke')
            fig.tight_layout(); fig.savefig(output/(name+'.png'),dpi=160); figures.append(name+'.png')
            if record.get('geometry_qualification')=='PROVISIONAL_USER_AUTHORIZED':
                lo,hi=config['source_bbox'];pad=.4*config['protocol']['reference_height_m']
                ax.set_xlim(lo[0]-pad,hi[0]+pad);ax.set_ylim(lo[2]-pad,hi[2]+pad)
                ax.set_title(f'{label}, near body; provisional geometry')
                fig.savefig(output/(name+'-near.png'),dpi=160,bbox_inches='tight');figures.append(name+'-near.png')
            plt.close(fig)
    if not polygons: warnings.append('Mesh/pressure/velocity sections unavailable: no successfully exported field data.')
    resources=_collect_resources(root)
    summary=_build_summary(root,resources)
    comparison='../geometry/comparison.png' if (root/'geometry/comparison.png').exists() else None
    body=f'<h1>RunFlow Phase 1.0 — {html.escape(record["execution_status"])}</h1><p>{html.escape(record["reason"])}</p><p>Scientific status: {html.escape(record.get("scientific_status",UNAVAILABLE))}. No ranking eligibility.</p>'
    if record.get('geometry_qualification')=='PROVISIONAL_USER_AUTHORIZED':
        body+='<p>現状の形状差を保留して実行した暫定計測。元の2mm条件を満たしたという意味ではありません。</p><p><a href="../fidelity-review.json">元の形状差とユーザーの実行指示</a></p>'
    body+='<h2>Execution and formal result</h2><dl>'
    for key in ('drag_N','Cd','CdA_m2'):
        value=record.get(key); body+=f'<dt>{key}</dt><dd>{value if value is not None else "null (not established)"}</dd>'
    for key in ('total_elapsed_wall_s','max_peak_rss_bytes','max_peak_output_bytes','cells'):
        body+=f'<dt>{key}</dt><dd>{summary[key] if summary[key] is not None else UNAVAILABLE}</dd>'
    body+='</dl><p>'+RSS_SCOPE+'</p>'
    for key in ('layer','yplus'):
        import json
        body+='<h2>'+key+'</h2><pre>'+html.escape(json.dumps(summary[key],indent=2))+'</pre>'
    if comparison: body+=f'<h2>Original and CFD surface candidate</h2><img src="{comparison}" width="800">'
    for name in figures: body+=f'<h2>{name}</h2><img src="{name}" width="800">'
    for warning in warnings: body+='<p>'+html.escape(warning)+'</p>'
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>RunFlow Phase 1.0</title>'+body,encoding='utf-8')
    write(output/'report.json',dict(execution_status=record['execution_status'],figures=figures,
        comparison=comparison,warnings=warnings,resources=resources,summary=summary,elapsed_s=time.monotonic()-started))
    return record
