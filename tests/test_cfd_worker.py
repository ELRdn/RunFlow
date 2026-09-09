import importlib.util
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('cfd_worker',Path(__file__).resolve().parents[1]/'scripts/cfd_worker.py')
worker=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(worker)


def test_openfoam_compact_uniform_label_list(tmp_path):
    file=tmp_path/'cellLevel'
    file.write_text('FoamFile {format ascii;}\n57959{0}\n')
    assert worker.labels(file)==[0]*57959
    file.write_text('FoamFile {format ascii;}\n3\n(0 4 5)')
    assert worker.labels(file)==[0,4,5]


def test_mpi_detached_descendant_and_pid_reuse(monkeypatch):
    table={10:dict(parent=1,start=100,state='S',rss=10),11:dict(parent=10,start=110,state='S',rss=20)}
    monkeypatch.setattr(worker,'process_table',lambda:table)
    known={}; assert sum(v['rss'] for v in worker.descendants(10,known).values())==30
    table.pop(10); table[11]['parent']=1
    assert 11 in worker.descendants(10,known)
    table[11]['start']=120
    assert not worker.descendants(10,known)


def test_cycle_solver_includes_potential_initialization_and_legacy_stays_single_step():
    mpi=['mpirun','-np','4']
    cycle={'solver_initialization':{'method':'potentialFoam','write_phi':False,'write_pressure':False}}
    assert worker.solver_stage_commands(cycle,mpi)==[
        (mpi+['potentialFoam','-parallel'],'potentialFoam.log'),
        (mpi+['foamRun','-parallel'],'foamRun.log'),
    ]
    assert worker.solver_stage_commands({},mpi)==[(mpi+['foamRun','-parallel'],'foamRun.log')]
