import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "run_phase1_full_cycle",
    Path(__file__).resolve().parents[1] / "scripts/run_phase1_full_cycle.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_remaining_budget_does_not_double_count_completed_stage_elapsed():
    request = {
        "execution_budget_s": 86400,
        "auxiliary_reserved_s": 3600,
        "prior_consumed_compute_s": 100,
    }
    ledger = {"repair_audit_compute_s": 200, "cycle_compute_s": 300}
    assert MODULE._remaining(request, ledger) == 82200


def test_audit_complete_requires_all_finished_artifacts(tmp_path):
    names = [
        "request.json", "source-to-candidate.json", "candidate-to-source.json",
        "projections.json", "views.json", "sections.json",
    ]
    for name in names:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert MODULE._audit_complete(tmp_path) is False

    for name in names[1:]:
        (tmp_path / name).write_text('{"complete": true}', encoding="utf-8")
    assert MODULE._audit_complete(tmp_path) is True


def test_done_includes_skipped_frames():
    ledger = {
        "attempts": [{"phase_index": 1}],
        "skipped": [{"phase_index": 4}],
    }
    assert MODULE._done(ledger) == {1, 4}


def test_recover_interrupted_archives_partial_frame_and_marker(tmp_path, monkeypatch):
    output = tmp_path / "campaign"
    output.mkdir()
    frame_root = output / "frame-01-001"
    frame_root.mkdir()
    (frame_root / "partial.obj").write_text("partial", encoding="utf-8")
    MODULE.write(output / "active.json", {
        "phase_index": 1, "pid": 987654321, "started_utc": "2026-09-09T00:00:00+00:00",
    })
    ledger = {"completion_status": "PAUSED", "recoveries": []}
    monkeypatch.setattr(MODULE, "_pid_is_running", lambda pid: False)

    recovery = MODULE._recover_interrupted(output, ledger)

    assert not (output / "active.json").exists()
    assert not frame_root.exists()
    archived = Path(recovery["archived_frame"])
    assert archived.is_dir()
    assert (archived / "partial.obj").read_text(encoding="utf-8") == "partial"
    assert Path(recovery["archived_active"]).is_file()
    assert ledger["completion_status"] == "RESUMING"
    assert ledger["recovered_interrupted_frame"] == 1


def test_recover_interrupted_refuses_live_marker(tmp_path, monkeypatch):
    output = tmp_path / "campaign"
    output.mkdir()
    MODULE.write(output / "active.json", {"phase_index": 1, "pid": 123, "started_utc": "now"})
    monkeypatch.setattr(MODULE, "_pid_is_running", lambda pid: True)

    with pytest.raises(RuntimeError, match="still running"):
        MODULE._recover_interrupted(output, {"completion_status": "PAUSED"})

    assert (output / "active.json").is_file()
