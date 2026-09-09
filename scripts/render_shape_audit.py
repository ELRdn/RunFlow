"""Private measured-geometry figures and component summaries for the shape audit."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize
import numpy as np
import shapely
from shapely.plotting import plot_polygon
from runflow.shape_audit import load_surface,SAMPLE_DTYPE,source_components


def polygons(geometry):
    if geometry.is_empty: return []
    if geometry.geom_type=='Polygon': return [geometry]
    return [p for child in geometry.geoms for p in polygons(child)]


def draw(ax,g,color,alpha=.6):
    for part in polygons(g):
        plot_polygon(part,ax=ax,add_points=False,color=color,alpha=alpha,linewidth=.3)


def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True); args=p.parse_args()
    root=args.root; figures=root/'figures'; figures.mkdir(exist_ok=True)
    projection=json.loads((root/'projections.json').read_text()) if (root/'projections.json').exists() else None
    if projection and projection['complete']:
        fig,axs=plt.subplots(1,3,figsize=(14,7),layout='constrained')
        geometries={}
        for ax,view in zip(axs,['front','side','top']):
            a=shapely.from_wkb((root/(view+'-source.wkb')).read_bytes())
            b=shapely.from_wkb((root/(view+'-candidate.wkb')).read_bytes())
            geometries[view]=(a,b)
            draw(ax,a.union(b),'#a1b1bc',.55); draw(ax,a.difference(b),'#c7274b',.9); draw(ax,b.difference(a),'#159f65',.9)
            ax.set_aspect('equal'); ax.autoscale()
            info=projection['views'][view]
            ax.set_title(f'{view} | area change {info["relative_change"]*100:+.3f}%')
            axes=info['axes']; ax.set_xlabel('XYZ'[axes[0]]+' [m]'); ax.set_ylabel('XYZ'[axes[1]]+' [m]')
        fig.suptitle('Silhouettes | red: lost; green: added | continuous projected-triangle union')
        fig.savefig(figures/'silhouettes.png',dpi=180); plt.close(fig)
        holes=[]
        for view,info in projection['views'].items():
            holes.extend((h['filled_mm2'],view,h) for h in info['source_holes_at_least_1_mm2'])
        holes=sorted(holes,key=lambda x:x[0],reverse=True)[:6]
        if holes:
            fig,axs=plt.subplots(2,3,figsize=(14,9),layout='constrained')
            for ax in axs.flat: ax.set_visible(False)
            for ax,(_,view,hole) in zip(axs.flat,holes):
                ax.set_visible(True); a,b=geometries[view]
                x0,y0,x1,y1=hole['bbox_m']; pad=max(.002,max(x1-x0,y1-y0)*.15)
                window=shapely.box(x0-pad,y0-pad,x1+pad,y1+pad)
                draw(ax,a.intersection(window),'#8aa3b5',.5)
                draw(ax,b.difference(a).intersection(window),'#e99128',.85)
                draw(ax,a.difference(b).intersection(window),'#c7274b',.7)
                ax.set_xlim(x0-pad,x1+pad); ax.set_ylim(y0-pad,y1+pad); ax.set_aspect('equal')
                ax.set_title(f'{view} | original hole {hole["area_mm2"]:.2f} mm2\nfilled {hole["filled_fraction"]*100:.1f}%')
                ax.set_xlabel('m'); ax.set_ylabel('m')
            fig.suptitle('Largest added coverage in enclosed projected gaps | orange: newly occupied')
            fig.savefig(figures/'projected-gaps.png',dpi=170); plt.close(fig)
    if (root/'views.json').exists():
        views=json.loads((root/'views.json').read_text())['views']
        fig,axs=plt.subplots(2,3,figsize=(15,11),layout='constrained')
        depthfig,depthaxs=plt.subplots(2,3,figsize=(15,11),layout='constrained')
        for ax,dax,(key,info) in zip(axs.flat,depthaxs.flat,views.items()):
            a=np.load(root/(key+'-source.npz'))['depth']; b=np.load(root/(key+'-candidate.npz'))['depth']
            common=np.isfinite(a)&np.isfinite(b)
            diff=np.where(common,np.abs(a-b)*1000,np.nan)
            im=ax.imshow(diff,origin='lower',extent=info['extent_m'],cmap='magma',vmin=0,vmax=10)
            ax.set_title(key+' | depth difference [mm]'); ax.set_aspect('equal')
            dax.imshow(np.ma.masked_invalid(a),origin='lower',extent=info['extent_m'],cmap='Blues')
            missing=np.isfinite(a)&~np.isfinite(b); added=~np.isfinite(a)&np.isfinite(b)
            rgba=np.zeros((*a.shape,4)); rgba[missing]=[.9,.05,.25,1]; rgba[added]=[.1,.7,.3,1]
            dax.imshow(rgba,origin='lower',extent=info['extent_m']); dax.set_title(key+' | source + silhouette loss/addition')
        fig.colorbar(im,ax=axs.ravel().tolist(),label='First-hit difference [mm], saturated at 10')
        fig.suptitle('Six-direction first-hit depth | 2mm ray grid; edge/background switching can amplify values')
        fig.savefig(figures/'depth-differences.png',dpi=160); plt.close(fig)
        depthfig.suptitle('Part-presence review | red: source-only pixels; green: candidate-only pixels')
        depthfig.savefig(figures/'part-presence.png',dpi=180); plt.close(depthfig)
    if (root/'sections.json').exists():
        section=json.loads((root/'sections.json').read_text())['sections']
        labels=[k[:-7] for k in section if k.endswith('-source')]
        fig,axs=plt.subplots(2,3,figsize=(14,10),layout='constrained')
        for ax,label in zip(axs.flat,labels):
            info=section[label+'-source']; axes=[i for i in range(3) if i!=info['axis']]
            for name,color in [('source','#247dc0'),('candidate','#e68721')]:
                lines=np.load(root/(label+'-'+name+'-section.npy'))[:,: ,axes]
                ax.add_collection(LineCollection(lines,colors=color,linewidths=.7,label=name))
            ax.autoscale(); ax.set_aspect('equal')
            ax.set_title(f'{label} | {"XYZ"[info["axis"]]}={info["value_m"]}m'); ax.legend(fontsize=8)
            ax.set_xlabel('XYZ'[axes[0]]+' [m]'); ax.set_ylabel('XYZ'[axes[1]]+' [m]')
        fig.suptitle('Selected geometric sections | blue: source; orange: candidate; no inside/outside assumption')
        fig.savefig(figures/'sections.png',dpi=180); plt.close(fig)
    if (root/'external-distances.json').exists():
        results=json.loads((root/'external-distances.json').read_text())['views']
        views=json.loads((root/'views.json').read_text())['views']
        fig,axs=plt.subplots(2,3,figsize=(15,11),layout='constrained')
        for ax,(key,info) in zip(axs.flat,results.items()):
            d=np.load(root/(key+'-external-nearest.npy'))*1000
            im=ax.imshow(np.ma.masked_invalid(d),origin='lower',extent=views[key]['extent_m'],
                         cmap='viridis',vmin=0,vmax=10)
            ax.set_title(f'{key} | visible sampled max {info["max_sampled_m"]*1000:.2f}mm')
            point=info['witness_m']; axes=views[key]['axes']
            ax.plot(point[axes[0]],point[axes[1]],'o',markerfacecolor='none',markeredgecolor='red',markersize=8)
        fig.colorbar(im,ax=axs.ravel().tolist(),label='Nearest candidate surface [mm], saturated at 10')
        fig.suptitle('Directly visible source points | six 2mm ray grids | red circles: sampled maxima')
        fig.savefig(figures/'external-surface-distances.png',dpi=180); plt.close(fig)
    if (root/'source-to-candidate.json').exists() and (root/'candidate-to-source.json').exists():
        source,candidate=[json.loads((root/(name+'.json')).read_text()) for name in ('source-to-candidate','candidate-to-source')]
        fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
        keys=['0.0005','0.001','0.002','0.005','0.01','0.02']; x=np.arange(len(keys))
        for offset,color,label,info in [(-.16,'#2879b0','Source to candidate',source),(.16,'#dc8626','Candidate to source',candidate)]:
            vals=[info['thresholds'][k]['estimated_fraction']*100 for k in keys]
            lower=[info['thresholds'][k]['definitely_over_fraction']*100 for k in keys]
            upper=[info['thresholds'][k]['possibly_over_fraction']*100 for k in keys]
            ax.bar(x+offset,vals,width=.3,color=color,label=label)
            ax.errorbar(x+offset,vals,yerr=[np.array(vals)-lower,np.array(upper)-vals],fmt='none',ecolor='#333',capsize=3)
        ax.set_xticks(x,[str(float(k)*1000) for k in keys]); ax.set_xlabel('Distance threshold [mm]')
        ax.set_ylabel('Triangle surface area above threshold [%]'); ax.legend()
        ax.set_title('Area-weighted distance estimates with whole-subtriangle coverage bounds')
        fig.savefig(figures/'distance-distribution.png',dpi=180); plt.close(fig)
        v,f=load_surface(root/'source'); labels=source_components(v,f); np.save(root/'source-component-labels.npy',labels)
        samples=np.memmap(root/'source-to-candidate.samples',dtype=SAMPLE_DTYPE,mode='r')
        face_area=np.bincount(samples['face'],weights=samples['area'],minlength=len(f))
        face_dsum=np.bincount(samples['face'],weights=samples['area'].astype(float)*samples['distance'],minlength=len(f))
        face_max=np.zeros(len(f)); np.maximum.at(face_max,samples['face'],samples['distance'])
        components=[]
        for label in np.unique(labels):
            indices=np.flatnonzero(labels==label); vertices=v[np.unique(f[indices])]
            area=float(face_area[indices].sum())
            if area<=0: continue
            components.append(dict(component=int(label),triangles=len(indices),area_m2=area,
                mean_distance_m=float(face_dsum[indices].sum()/area),max_sampled_distance_m=float(face_max[indices].max()),
                bbox_m=[vertices.min(axis=0).tolist(),vertices.max(axis=0).tolist()]))
        (root/'source-components.json').write_text(json.dumps(dict(components=sorted(components,key=lambda c:c['area_m2'],reverse=True),
            label_basis='Connectivity using exact coincident positions; not semantic body parts'),indent=2),encoding='utf-8')
        np.savez_compressed(root/'source-face-distances.npz',area=face_area,mean=np.divide(face_dsum,face_area,out=np.zeros(len(f)),where=face_area>0),maximum=face_max)
    print('AUDIT_FIGURES_READY',figures,flush=True)


if __name__=='__main__': main()
