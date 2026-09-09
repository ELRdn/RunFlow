"""Foundation 14 case writer; only generated private cases are written."""
import math
from pathlib import Path
import shutil


def foam(name, body, cls='dictionary'):
    return f'FoamFile {{ version 2.0; format ascii; class {cls}; object {name}; }}\n'+body+'\n'


WALL_TREATMENTS=('reference-switching','omega-blended')


def wall_record(treatment):
    if treatment not in WALL_TREATMENTS:raise ValueError('Unknown wall treatment')
    return dict(treatment=treatment,omega_blended=treatment=='omega-blended',nut_function='nutkWallFunction',
        omega_function='omegaWallFunction',accuracy_status='UNVALIDATED',
        note='Blending is a near-wall model option. The upstream header reports switching as more accurate at 10<yPlus<30 with high-Re wall functions; convergence is not proof of accuracy.')


def build(case, snapshot, protocol, upstream, numerics='motorbike-simplec',wall_treatment='reference-switching'):
    from .cfd_numerics import solution,description,schemes
    numerical_record=description(numerics)
    wall=wall_record(wall_treatment)
    case=Path(case); h=protocol['reference_height_m']; mesh=protocol['mesh']; domain=protocol['domain']
    lo=[min(v[i] for v in snapshot['vertices']) for i in range(3)]
    hi=[max(v[i] for v in snapshot['vertices']) for i in range(3)]
    low=[lo[0]-domain['downstream_H']*h,lo[1]-domain['lateral_H']*h,lo[2]-domain['vertical_H']*h]
    high=[hi[0]+domain['upstream_H']*h,hi[1]+domain['lateral_H']*h,hi[2]+domain['vertical_H']*h]
    def put(path, text):
        target=case/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text,encoding='ascii')
    def vec(v): return '('+' '.join(f'{x:.12g}' for x in v)+')'
    vertices=[(low[0],low[1],low[2]),(high[0],low[1],low[2]),(high[0],high[1],low[2]),(low[0],high[1],low[2]),
              (low[0],low[1],high[2]),(high[0],low[1],high[2]),(high[0],high[1],high[2]),(low[0],high[1],high[2])]
    cells=[math.ceil((high[i]-low[i])/(h*mesh['background_H'])) for i in range(3)]
    boundary='inlet {type patch; faces ((1 2 6 5));} outlet {type patch; faces ((0 4 7 3));}'
    for name,face in [('sideMin','0 1 5 4'),('sideMax','3 7 6 2'),('bottom','0 3 2 1'),('top','4 5 6 7')]:
        boundary+=f'{name} {{type symmetryPlane; faces (({face}));}}'
    put('system/blockMeshDict',foam('blockMeshDict',f'convertToMeters 1;\nvertices ( {" ".join(map(vec,vertices))} );\nblocks (hex (0 1 2 3 4 5 6 7) ({" ".join(map(str,cells))}) simpleGrading (1 1 1));\nedges (); boundary ({boundary});'))
    # Pressure is kinematic pressure; forces performs the one required rhoInf conversion.
    u=vec([x*protocol['speed_m_s'] for x in protocol['inlet_direction']])
    k=1.5*(protocol['speed_m_s']*protocol['turbulence_intensity'])**2
    omega=math.sqrt(k)/(.09**.25*protocol['turbulence_length_height_ratio']*h)
    fields={
        'U':('volVectorField','[0 1 -1 0 0 0 0]',u,'fixedValue',f'value uniform {u};','inletOutlet',f'inletValue uniform {u}; value uniform {u};','noSlip',''),
        'p':('volScalarField','[0 2 -2 0 0 0 0]','0','zeroGradient','','fixedValue','value uniform 0;','zeroGradient',''),
        'k':('volScalarField','[0 2 -2 0 0 0 0]',str(k),'fixedValue',f'value uniform {k};','inletOutlet',f'inletValue uniform {k}; value uniform {k};','kqRWallFunction',f'value uniform {k};'),
        'omega':('volScalarField','[0 0 -1 0 0 0 0]',str(omega),'fixedValue',f'value uniform {omega};','inletOutlet',f'inletValue uniform {omega}; value uniform {omega};','omegaWallFunction',f'value uniform {omega};'),
        'nut':('volScalarField','[0 2 -1 0 0 0 0]','0','calculated','value uniform 0;','calculated','value uniform 0;','nutkWallFunction','value uniform 0;')}
    for name,(cls,dim,initial,intype,inspec,outtype,outspec,walltype,wallspec) in fields.items():
        if name=='omega' and wall['omega_blended']:wallspec='blended true; '+wallspec
        body=f'dimensions {dim}; internalField uniform {initial}; boundaryField {{ inlet {{type {intype}; {inspec}}} outlet {{type {outtype}; {outspec}}} "oguri.*" {{type {walltype}; {wallspec}}}'
        body+=' "(sideMin|sideMax|bottom|top)" {type symmetryPlane;} "procBoundary.*" {type processor;} }'
        put('0/'+name,foam(name,body,cls))
    put('constant/physicalProperties',foam('physicalProperties',f'viscosityModel constant; nu {protocol["kinematic_viscosity_m2_s"]};'))
    put('constant/momentumTransport',foam('momentumTransport','simulationType RAS; RAS {model kOmegaSST; turbulence on;}'))
    put('system/decomposeParDict',foam('decomposeParDict',f'numberOfSubdomains {protocol["limits"]["processes"]}; method scotch;'))
    for name in ('fvSchemes','fvSolution','meshQualityDict'):
        text=upstream['files']['tutorial/system/'+name]
        if name=='fvSolution':text=solution(text,numerics)
        if name=='fvSchemes':text=schemes(text,numerics)
        if name=='meshQualityDict':
            # The upstream motorBike dictionary permits boundary skewness 20,
            # but stock checkMesh rejects any face above 4. Use the stricter
            # final acceptance limit during snapping and layer generation too.
            text+='\n// RunFlow: match stock checkMesh acceptance for boundary faces.\nmaxBoundarySkewness 4;\n'
        put('system/'+name,text)
    put('system/surfaceFeaturesDict',foam('surfaceFeaturesDict','surfaces ("oguri.obj"); includedAngle 150; subsetFeatures {nonManifoldEdges no; openEdges yes;}'))
    wake_lo=[lo[0]-5*h,lo[1]-h,lo[2]-h]; wake_hi=[hi[0],hi[1]+h,hi[2]+h]
    diagnostic=protocol.get('diagnostic_refinement')
    local_geometry='';local_region=''
    if diagnostic:
        if any(not low[i]<=diagnostic['box_min_m'][i]<diagnostic['box_max_m'][i]<=high[i] for i in range(3)):
            raise ValueError('Local fluid-grid diagnostic must lie within the CFD domain')
        local_geometry=f'coatTip {{type box; min {vec(diagnostic["box_min_m"])}; max {vec(diagnostic["box_max_m"])};}}'
        local_region=f'coatTip {{mode inside; level {diagnostic["level"]};}}'
    inside=[high[0]-.137*h,high[1]-.153*h,high[2]-.171*h]
    snappy=f'''
castellatedMesh true; snap true; addLayers true;
geometry {{oguri {{type triSurface; file "oguri.obj";}}
wake {{type box; min {vec(wake_lo)}; max {vec(wake_hi)};}} {local_geometry}}}
castellatedMeshControls {{
maxLocalCells {mesh['max_cells']}; maxGlobalCells {mesh['max_cells']}; minRefinementCells 0;
maxLoadUnbalance 0.1; nCellsBetweenLevels 3;
features ({{file "oguri.eMesh"; level {mesh['surface_level']};}});
refinementSurfaces {{oguri {{level ({mesh['surface_level']} {mesh['surface_level']}); patchInfo {{type wall; inGroups (oguriGroup);}}}}}}
resolveFeatureAngle 30;
refinementRegions {{wake {{mode inside; level {mesh['wake_level']};}}{local_region}}}
insidePoint {vec(inside)}; allowFreeStandingZoneFaces false;
}}
snapControls {{nSmoothPatch 3; tolerance 2; nSolveIter 30; nRelaxIter 5; nFeatureSnapIter 10; implicitFeatureSnap false; explicitFeatureSnap true; multiRegionFeatureSnap false;}}
addLayersControls {{
relativeSizes true; layers {{"oguri.*" {{nSurfaceLayers {mesh['layers']};}}}}
expansionRatio {mesh['layer_expansion']}; firstLayerThickness {mesh['first_layer_fraction']}; minThickness 0.1;
nGrow 0; featureAngle 100; slipFeatureAngle 30; nRelaxIter 3;
nSmoothSurfaceNormals 1; nSmoothNormals 3; nSmoothThickness 10;
maxFaceThicknessRatio 0.5; maxThicknessToMedialRatio 0.3; minMedianAxisAngle 90;
nBufferCellsNoExtrude 0; nLayerIter 50;
}}
meshQualityControls {{#include "meshQualityDict"}}
writeFlags (scalarLevels layerSets layerFields); mergeTolerance 1e-6;
'''
    # Preprocessor directives must occupy their own line.
    snappy=snappy.replace('{#include "meshQualityDict"}', '{\n#include "meshQualityDict"\n}')
    put('system/snappyHexMeshDict',foam('snappyHexMeshDict',snappy))
    functions='''
forces {type forces; libs ("libforces.so"); patches ("oguri.*"); rho rhoInf; rhoInf 1.2; CofR (0 0 0); writeControl timeStep; writeInterval 1;}
inletFlux {type surfaceFieldValue; libs ("libfieldFunctionObjects.so"); patch inlet; operation sum; fields (phi); writeFields false; writeControl timeStep; writeInterval 1;}
outletFlux {type surfaceFieldValue; libs ("libfieldFunctionObjects.so"); patch outlet; operation sum; fields (phi); writeFields false; writeControl timeStep; writeInterval 1;}
yPlus {type yPlus; libs ("libfieldFunctionObjects.so"); writeControl writeTime;}
'''
    put('system/controlDict',foam('controlDict',f'''
solver incompressibleFluid;
startFrom startTime; startTime 0; stopAt endTime; endTime {protocol['convergence']['max_iterations']}; deltaT 1;
writeControl timeStep; writeInterval 100; purgeWrite 2; writeFormat ascii; writePrecision 10;
writeCompression off; timeFormat general; timePrecision 10; runTimeModifiable true;
functions {{{functions}}}
'''))
    return dict(source_bbox=[lo,hi],domain_bbox=[low,high],background_cells=cells,
        inlet_k=k,inlet_omega=omega,ground=False,boundary_skewness_limit=4,numerics=numerical_record,wall_treatment=wall,
        diagnostic_volume_refinement=diagnostic)
