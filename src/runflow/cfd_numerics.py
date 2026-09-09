"""Explicit, recorded iteration settings; physics and convergence gates stay fixed."""
import re

PROFILES = ('motorbike-simplec', 'motorbike-simplec-upwind', 'standard-simple', 'standard-simple-limited', 'standard-simple-upwind',
            'standard-simple-upwind-damped', 'standard-simple-upwind-damped-nonorth',
            'standard-simple-upwind-damped-nonorth-tight',
            'standard-simple-upwind-damped-nonorth-tight-limiteddiffusion',
            'standard-simple-upwind-damped-nonorth-tight-turbdamped',
            'standard-simple-upwind-damped-nonorth-tight-pressurelsq')


def solution(text, profile):
    if profile not in PROFILES:
        raise ValueError('Unknown numerical profile: '+str(profile))
    if profile.startswith('motorbike-simplec'):
        return text
    # This adapter intentionally accepts only the pinned upstream layout. A
    # changed upstream must be reviewed instead of silently applying a patch.
    substitutions = (
        (r'\bconsistent\s+yes\s*;', 'consistent no;'),
        (r'\bU\s+0\.9\s*;', 'U 0.5;' if profile.startswith('standard-simple-upwind-damped') else 'U 0.7;'),
        (r'\brelaxationFactors\s*\{',
         'relaxationFactors\n{\n    fields { p 0.3; }'),
    )
    if '-nonorth' in profile:
        substitutions+=((r'\bnNonOrthogonalCorrectors\s+0\s*;', 'nNonOrthogonalCorrectors 1;'),)
    for pattern, replacement in substitutions:
        text, count = re.subn(pattern, replacement, text)
        if count != 1:
            raise ValueError('Numerical profile requires the pinned motorBike layout')
    if '-tight' in profile:
        for pattern,replacement in ((r'\btolerance\s+1e-[78]\s*;','tolerance 1e-10;'),
                                    (r'\brelTol\s+0\.(?:01|1)\s*;','relTol 0;')):
            text,count=re.subn(pattern,replacement,text)
            if count!=4:raise ValueError('Tight inner solves require four pinned solver blocks')
    if profile.endswith('-turbdamped'):
        for field in ('k','omega'):
            text,count=re.subn(r'\b'+field+r'\s+0\.5\s*;',field+' 0.3;',text)
            if count!=1:raise ValueError('Turbulence damping requires pinned relaxation factors')
    return '// RunFlow standard SIMPLE; p=0.3; equation relaxation recorded in case-design.json.\n'+text


def description(profile):
    if profile not in PROFILES:
        raise ValueError('Unknown numerical profile: '+str(profile))
    return dict(profile=profile, algorithm='SIMPLEC' if profile.startswith('motorbike-simplec') else 'SIMPLE',
        pressure_field_relaxation=None if profile.startswith('motorbike-simplec') else .3,
        velocity_equation_relaxation=.9 if profile.startswith('motorbike-simplec') else (.5 if profile.startswith('standard-simple-upwind-damped') else .7),
        turbulence_equation_relaxation=.3 if profile.endswith('-turbdamped') else .5, non_orthogonal_correctors=1 if '-nonorth' in profile else 0,
        advection=('bounded Gauss upwind' if 'upwind' in profile else
            ('bounded Gauss limitedLinearV 1' if profile=='standard-simple-limited' else 'bounded Gauss linearUpwindV grad(U)')),
        linear_tolerances={f:(1e-10 if '-tight' in profile else (1e-7 if f=='p' else 1e-8)) for f in ('p','U','k','omega')},
        linear_relative_tolerances={f:(0 if '-tight' in profile else (.01 if f=='p' else .1)) for f in ('p','U','k','omega')},
        non_orthogonal_scheme='limited corrected 0.5' if profile.endswith('-limiteddiffusion') else 'corrected',
        pressure_gradient='leastSquares' if profile.endswith('-pressurelsq') else 'Gauss linear',
        spatial_accuracy_note='FIRST_ORDER_UPWIND_NUMERICAL_DIFFUSION_UNVALIDATED' if 'upwind' in profile else 'SPATIAL_SENSITIVITY_UNVALIDATED',
        convergence_thresholds_changed=False,
        reference='https://doc.cfd.direct/notes/cfd-general-principles/steady-state-convergence')


def schemes(text, profile):
    description(profile)
    if profile!='standard-simple-limited' and 'upwind' not in profile:return text
    target=description(profile)['advection']
    text,count=re.subn(r'\bdiv\(phi,U\)\s+bounded\s+Gauss\s+linearUpwindV\s+grad\(U\)\s*;',
        'div(phi,U) '+target+';',text)
    if count!=1:raise ValueError('Numerical profile requires the pinned velocity advection scheme')
    if profile.endswith('-limiteddiffusion'):
        # Limit the explicit nonorthogonal correction, retaining the implicit
        # diffusion operator. This is a spatial approximation, not a gate change.
        for pattern,replacement in (
            (r'(laplacianSchemes\s*\{\s*default\s+Gauss linear )corrected\s*;',r'\1limited corrected 0.5;'),
            (r'(snGradSchemes\s*\{\s*default\s+)corrected\s*;',r'\1limited corrected 0.5;')):
            text,count=re.subn(pattern,replacement,text)
            if count!=1:raise ValueError('Limited diffusion requires pinned nonorthogonal schemes')
    if profile.endswith('-pressurelsq'):
        if re.search(r'\bgrad\(p\)',text):raise ValueError('Unexpected explicit pressure gradient')
        text,count=re.subn(r'\bgradSchemes\s*\{','gradSchemes\n{\n    grad(p) leastSquares;',text)
        if count!=1:raise ValueError('Pressure gradient requires pinned gradSchemes')
    return '// RunFlow velocity advection profile: '+profile+' (spatial accuracy unvalidated).\n'+text
