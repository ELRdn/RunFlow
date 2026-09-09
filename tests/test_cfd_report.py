import time
from runflow.core import write,read
from runflow.cfd_report import create


def test_blocked_report_never_invents_fields_or_coefficients(tmp_path):
    write(tmp_path/'state.json',dict(started_epoch=time.time()-12,updated_epoch=time.time()-2))
    write(tmp_path/'result.json',dict(execution_status='BLOCKED',reason='distance > 2mm',drag_N=None,Cd=None,CdA_m2=None))
    write(tmp_path/'blender.log.execution.json',dict(elapsed_s=10,peak_rss_bytes=100,peak_output_bytes=200,returncode=0,reason=None))
    create(tmp_path)
    report=read(tmp_path/'report/report.json'); summary=report['summary']
    assert summary['total_elapsed_wall_s']>=12 and summary['max_peak_rss_bytes']==100
    assert summary['cells'] is None and summary['yplus']['status']=='unavailable'
    assert not report['figures'] and len(report['warnings'])==3
    page=(tmp_path/'report/index.html').read_text()
    assert 'null (not established)' in page and 'distance &gt; 2mm' in page


def test_layer_average_is_not_face_generation_rate(tmp_path):
    from runflow.cfd_report import _layer_diagnostics
    (tmp_path/'snappyHexMesh.log').write_text('patch faces layers overall thickness\noguri 100 2.5 0.003 80\n')
    value=_layer_diagnostics(tmp_path)
    assert value['patches'][0]['mean_layers']==2.5
    assert value['face_coverage_fraction'] is None
    (tmp_path/'snappyHexMesh.log').write_text('oguri 16 0 0 0\n')
    assert _layer_diagnostics(tmp_path)['face_coverage_fraction']==0


def test_internal_vtk_uses_latest_rank_files_without_global_aliases(tmp_path):
    from runflow.cfd_report import internal_vtk_files
    names=['processor0/VTK/processor0_2.vtk','processor0/VTK/processor0_3.vtk',
        'processor1/VTK/processor1_3.vtk','VTK/processor0_processor0_3.vtk',
        'processor0/VTK/oguri/oguri_3.vtk']
    for name in names:
        path=tmp_path/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('fixture')
    assert [p.relative_to(tmp_path).as_posix() for p in internal_vtk_files(tmp_path)]==[
        'processor0/VTK/processor0_3.vtk','processor1/VTK/processor1_3.vtk']
