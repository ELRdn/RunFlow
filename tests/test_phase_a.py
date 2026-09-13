"""Phase A tests: projection cache, audit contract, family semantics, runner."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
import shapely

from runflow import projection_cache
from runflow.audit_contract import (CANONICAL_NAME, MERGED_NAME, PRIOR_NAME, REQUIRED_VIEWS,
                                    load_authoritative_projections, load_view_file, merge_views,
                                    promote, validate_projections)
from runflow.cfd_cycle import apply_execution, cycle_family
from runflow.execution_profile import resolve, resolve_pair
from runflow.scratch import (copy_back_frame, job_commit_limit, verify_manifest)
from runflow.shape_audit import cache_surface

REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "scripts" / "audit_shape_projection.py"
sys.path.insert(0, str(REPO / "scripts"))

from run_phase1_parallel_cycle import aggregate, assign


def _view(source, candidate, axes, grid=0.0):
    return dict(source_m2=source, candidate_m2=candidate,
                relative_change_abs=abs(candidate - source) / source,
                iou=0.9995, axes=list(axes), precision_grid_m=grid)


def _document(rows=None, complete=True):
    rows = rows or {name: _view(1.0, 1.001, axes)
                    for name, axes in (("front", (1, 2)), ("side", (0, 2)), ("top", (0, 1)))}
    return {"views": rows, "complete": complete}


# --- A2: projection cache -------------------------------------------------

def test_projection_cache_roundtrip(tmp_path):
    payload = projection_cache.cache_payload(geometry_sha256="a" * 64, view="front",
                                             axes=(1, 2), grid_m=1e-9, chunk_size=20000)
    key = projection_cache.cache_key(payload)
    assert projection_cache.lookup(tmp_path, key, payload) is None
    geometry = shapely.box(0, 0, 1, 1)
    projection_cache.store(tmp_path, key, payload, geometry)
    cached = projection_cache.lookup(tmp_path, key, payload)
    assert cached is not None and cached.area == pytest.approx(1.0)


def test_projection_cache_identity_changes_with_inputs():
    base = dict(geometry_sha256="a" * 64, view="front", axes=(1, 2), grid_m=1e-9, chunk_size=20000)
    keys = {projection_cache.cache_key(projection_cache.cache_payload(**base))}
    for change in (dict(view="side"), dict(grid_m=1e-7), dict(axes=(0, 2)),
                   dict(chunk_size=1000), dict(geometry_sha256="b" * 64)):
        keys.add(projection_cache.cache_key(projection_cache.cache_payload(**dict(base, **change))))
    assert len(keys) == 6


def test_projection_cache_detects_corruption(tmp_path):
    payload = projection_cache.cache_payload(geometry_sha256="a" * 64, view="front",
                                             axes=(1, 2), grid_m=1e-9, chunk_size=20000)
    key = projection_cache.cache_key(payload)
    projection_cache.store(tmp_path, key, payload, shapely.box(0, 0, 1, 1))
    wkb = projection_cache.cache_dir(tmp_path) / (key + ".wkb")
    wkb.write_bytes(b"not-a-wkb")
    assert projection_cache.lookup(tmp_path, key, payload) is None


def test_projection_cache_rejects_version_change(tmp_path):
    payload = projection_cache.cache_payload(geometry_sha256="a" * 64, view="front",
                                             axes=(1, 2), grid_m=1e-9, chunk_size=20000)
    key = projection_cache.cache_key(payload)
    projection_cache.store(tmp_path, key, payload, shapely.box(0, 0, 1, 1))
    changed = dict(payload, algorithm="project_mesh-hierarchical-union-2")
    assert projection_cache.lookup(tmp_path, key, changed) is None


def test_projection_cache_empty_geometry_is_a_miss(tmp_path):
    payload = projection_cache.cache_payload(geometry_sha256="a" * 64, view="front",
                                             axes=(1, 2), grid_m=1e-9, chunk_size=20000)
    key = projection_cache.cache_key(payload)
    projection_cache.store(tmp_path, key, payload, shapely.from_wkt("GEOMETRYCOLLECTION EMPTY"))
    assert projection_cache.lookup(tmp_path, key, payload) is None


# --- A5: audit contract ---------------------------------------------------

def test_validate_projections_rejects_incomplete_and_missing_views():
    with pytest.raises(ValueError):
        validate_projections(_document(complete=False))
    rows = {name: _view(1.0, 1.001, (1, 2)) for name in ("front", "side")}
    with pytest.raises(ValueError):
        validate_projections({"views": rows, "complete": True})


def test_validate_projections_rejects_wrong_axes_and_bad_areas():
    rows = {name: _view(1.0, 1.001, axes) for name, axes in
            (("front", (1, 2)), ("side", (0, 2)), ("top", (0, 1)))}
    rows["side"]["axes"] = [1, 2]
    with pytest.raises(ValueError):
        validate_projections({"views": rows, "complete": True})
    rows["side"]["axes"] = [0, 2]
    rows["top"]["source_m2"] = 0.0
    with pytest.raises(ValueError):
        validate_projections({"views": rows, "complete": True})


def test_merge_views_orders_deterministically():
    rows = {name: _view(1.0, 1.001, axes) for name, axes in
            (("top", (0, 1)), ("front", (1, 2)), ("side", (0, 2)))}
    merged = merge_views(rows)
    assert list(merged["views"]) == list(REQUIRED_VIEWS)
    assert merged["complete"] is True


def test_load_authoritative_prefers_canonical(tmp_path):
    canonical = _document()
    (tmp_path / CANONICAL_NAME).write_text(json.dumps(canonical), encoding="utf-8")
    (tmp_path / MERGED_NAME).write_text(json.dumps(_document()), encoding="utf-8")
    document, source = load_authoritative_projections(tmp_path)
    assert source == CANONICAL_NAME and document["complete"] is True


def test_load_authoritative_accepts_verified_merged(tmp_path):
    (tmp_path / CANONICAL_NAME).write_text(json.dumps({"views": {}, "complete": False}),
                                           encoding="utf-8")
    base = tmp_path / "projection-top.json"
    base.write_text("{}", encoding="utf-8")
    from runflow.scratch import file_sha
    merged = _document()
    merged["inputs"] = {base.name: file_sha(base)}
    (tmp_path / MERGED_NAME).write_text(json.dumps(merged), encoding="utf-8")
    document, source = load_authoritative_projections(tmp_path)
    assert source == MERGED_NAME and document["complete"] is True


def test_load_authoritative_rejects_unverified_or_corrupt_merged(tmp_path):
    (tmp_path / CANONICAL_NAME).write_text(json.dumps({"views": {}, "complete": False}),
                                           encoding="utf-8")
    base = tmp_path / "projection-top.json"
    base.write_text("{}", encoding="utf-8")
    merged = _document()
    merged["inputs"] = {base.name: "0" * 64}
    (tmp_path / MERGED_NAME).write_text(json.dumps(merged), encoding="utf-8")
    with pytest.raises(ValueError):
        load_authoritative_projections(tmp_path)
    (tmp_path / MERGED_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_authoritative_projections(tmp_path)


def test_load_authoritative_rejects_when_nothing_is_valid(tmp_path):
    (tmp_path / CANONICAL_NAME).write_text(json.dumps({"views": {}, "complete": False}),
                                           encoding="utf-8")
    with pytest.raises(ValueError):
        load_authoritative_projections(tmp_path)


def test_promote_from_merged_archives_prior(tmp_path):
    (tmp_path / CANONICAL_NAME).write_text(json.dumps({"views": {}, "complete": False}),
                                           encoding="utf-8")
    base = tmp_path / "projection-top.json"
    base.write_text("{}", encoding="utf-8")
    from runflow.scratch import file_sha
    merged = _document()
    merged["inputs"] = {base.name: file_sha(base)}
    (tmp_path / MERGED_NAME).write_text(json.dumps(merged), encoding="utf-8")
    result = promote(tmp_path)
    assert result["promoted"] is True
    assert (tmp_path / PRIOR_NAME).is_file()
    document = json.loads((tmp_path / CANONICAL_NAME).read_text(encoding="utf-8"))
    validate_projections(document)
    assert document["promotion"]["prior"][CANONICAL_NAME] == result["prior"][CANONICAL_NAME]
    again = promote(tmp_path)
    assert again["promoted"] is False


def test_promote_from_per_view_files(tmp_path):
    for view, axes in (("front", (1, 2)), ("side", (0, 2)), ("top", (0, 1))):
        document = {"views": {view: _view(1.0, 1.001, axes)}, "complete": True}
        (tmp_path / ("projection-" + view + ".json")).write_text(
            json.dumps(document), encoding="utf-8")
    assert load_view_file(tmp_path / "projection-front.json", "front")["source_m2"] == 1.0
    result = promote(tmp_path)
    assert result["promoted"] is True
    validate_projections(json.loads((tmp_path / CANONICAL_NAME).read_text(encoding="utf-8")))


def test_promote_refuses_without_evidence(tmp_path):
    with pytest.raises(ValueError):
        promote(tmp_path)


# --- A6: family semantics -------------------------------------------------

def _protocol(processes=4):
    return dict(schema_version="phase1-provisional-1", frame=3, speed_m_s=20,
                geometry=dict(mode="voxel_remesh_0.9mm_fullbody", voxel_m=0.0009),
                mesh=dict(surface_level=5), convergence=dict(min_iterations=300),
                limits=dict(processes=processes, memory_bytes=12 * 1024 ** 3,
                            output_bytes=10 * 1024 ** 3, geometry_s=600, mesh_s=1200,
                            solver_s=1500, report_s=300, total_s=3600))


def test_cycle_family_ignores_execution_limits():
    assert cycle_family(_protocol(4)) == cycle_family(_protocol(16))
    raised = apply_execution(_protocol(4), dict(processes=8))
    assert cycle_family(raised) == cycle_family(_protocol(4))
    assert raised["limits"]["processes"] == 8


def test_cycle_family_changes_with_scientific_input():
    other = _protocol()
    other["speed_m_s"] = 21
    assert cycle_family(other) != cycle_family(_protocol())
    mesh = _protocol()
    mesh["mesh"] = dict(surface_level=6)
    assert cycle_family(mesh) != cycle_family(_protocol())


def test_cycle_family_ignores_per_frame_repair_provenance():
    """Per-frame repair route is logged provenance, not a comparison condition."""
    first = _protocol()
    first["geometry"] = dict(mode="saved_local_repair_candidate", voxel_m=0.0009,
                             local_weld_m=1e-6, fidelity_gate="FOUNDATION_AND_SHAPE_AUDIT_PASS",
                             repair_method="numpy_foundation_contact_weld_diagnostic_v1",
                             repair_max_weld_m=0.001)
    second = _protocol()
    second["geometry"] = dict(first["geometry"],
                              repair_method="numpy_foundation_contact_weld_safe_v1",
                              repair_max_weld_m=0.002)
    assert cycle_family(first) == cycle_family(second)
    # The geometry pipeline itself still separates families.
    third = _protocol()
    third["geometry"] = dict(first["geometry"], voxel_m=0.0008)
    fourth = _protocol()
    fourth["geometry"] = dict(first["geometry"], fidelity_gate="OTHER")
    assert cycle_family(third) != cycle_family(first)
    assert cycle_family(fourth) != cycle_family(first)


def test_apply_execution_rejects_non_execution_fields():
    with pytest.raises(ValueError):
        apply_execution(_protocol(), dict(speed_m_s=21))
    with pytest.raises(ValueError):
        apply_execution(_protocol(), dict(processes=0))
    with pytest.raises(ValueError):
        apply_execution(_protocol(), {})


def test_execution_profile_rejects_oversubscription():
    profile = resolve("batch", host_logical=24)
    assert profile["workers"] == 2 and profile["ranks"] == 8
    assert profile["threads_per_worker"] == 11
    with pytest.raises(ValueError):
        resolve_pair(8, 8, host_logical=24)
    with pytest.raises(ValueError):
        resolve("does-not-exist")


# --- A7: parallel runner --------------------------------------------------

def test_parallel_assign_is_deterministic():
    groups = assign(list(range(8)), 3)
    assert groups == {0: [0, 3, 6], 1: [1, 4, 7], 2: [2, 5]}
    assert assign(list(range(32)), 4)[0] == [0, 4, 8, 12, 16, 20, 24, 28]


def _worker(tmp_path, index, frames, family):
    root = tmp_path / ("worker-%02d" % index)
    root.mkdir(parents=True)
    attempts = []
    for frame in frames:
        label = "frame-%02d-001" % frame
        (root / label).mkdir()
        (root / label / "result.json").write_text(
            json.dumps({"execution_status": "PASS", "comparison_family_sha256": family}),
            encoding="utf-8")
        attempts.append(dict(phase_index=frame, label=label, status="PASS",
                             drag_N=90.0, Cd=0.78, execution_elapsed_s=600.0))
    (root / "campaign.json").write_text(json.dumps(
        {"completion_status": "COMPLETE_REQUESTED_FRAMES", "attempts": attempts}),
        encoding="utf-8")
    return root


def test_parallel_aggregate_rejects_mixed_families(tmp_path):
    roots = [_worker(tmp_path, 0, [0], "a" * 64), _worker(tmp_path, 1, [1], "b" * 64)]
    with pytest.raises(ValueError):
        aggregate(tmp_path, roots)


def test_parallel_aggregate_reads_isolated_ledgers(tmp_path):
    roots = [_worker(tmp_path, 0, [0, 2], "a" * 64), _worker(tmp_path, 1, [1], "a" * 64)]
    summary = aggregate(tmp_path, roots)
    assert summary["pass_count"] == 3
    assert summary["families"] == ["a" * 64]
    assert summary["mean_drag_N"] == pytest.approx(90.0)
    assert (tmp_path / "parallel-campaign.json").is_file()


# --- A4: scratch ----------------------------------------------------------

def test_scratch_copy_back_excludes_scratch_only_trees(tmp_path):
    frame = tmp_path / "scratch" / "frame-00-001"
    (frame / "case" / "constant").mkdir(parents=True)
    (frame / "case" / "constant" / "big").write_text("x" * 10, encoding="utf-8")
    (frame / "report").mkdir()
    (frame / "report" / "report.json").write_text("{}", encoding="utf-8")
    (frame / "result.json").write_text('{"execution_status": "PASS"}', encoding="utf-8")
    archive = tmp_path / "archive" / "frame-00-001"
    manifest = copy_back_frame(frame, archive)
    assert "result.json" in manifest["files"]
    assert "report/report.json" in manifest["files"]
    assert not (archive / "case").exists()
    assert verify_manifest(archive)["files"] == manifest["files"]
    (archive / "result.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError):
        verify_manifest(archive)


def test_job_commit_limit_split():
    assert job_commit_limit(80 * 1024 ** 3, 4) == 20 * 1024 ** 3
    with pytest.raises(ValueError):
        job_commit_limit(80, 0)


# --- A1/A2/A3: audit CLI --------------------------------------------------

def _write_obj(path, vertices, faces):
    lines = ["v %.6f %.6f %.6f" % tuple(v) for v in vertices]
    lines += ["f %d %d %d" % tuple(index + 1 for index in face) for face in faces]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def _cube(scale=1.0):
    keys = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    index = {point: number for number, point in enumerate(keys)}
    vertices = [(x * scale, y * scale, z * scale) for (x, y, z) in keys]
    quads = [((0,0,0),(1,0,0),(1,1,0),(0,1,0)), ((0,0,1),(0,1,1),(1,1,1),(1,0,1)),
             ((0,0,0),(0,0,1),(1,0,1),(1,0,0)), ((0,1,0),(1,1,0),(1,1,1),(0,1,1)),
             ((0,0,0),(0,1,0),(0,1,1),(0,0,1)), ((1,0,0),(1,0,1),(1,1,1),(1,1,0))]
    faces = []
    for quad in quads:
        ids = [index[point] for point in quad]
        faces += [[ids[0], ids[1], ids[2]], [ids[0], ids[2], ids[3]]]
    return vertices, faces


def _surfaces(tmp_path):
    import hashlib
    root = tmp_path / "audit"
    root.mkdir(parents=True)
    for name, scale in (("source", 1.0), ("candidate", 1.005)):
        obj = root / (name + ".obj")
        _write_obj(obj, *_cube(scale))
        digest = hashlib.sha256(obj.read_bytes()).hexdigest()
        cache_surface(obj, root / name, digest)
    return root


def _run_audit(root, extra):
    return subprocess.run([sys.executable, str(AUDIT), "--root", str(root), *extra],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def test_audit_cli_guard_and_benchmark_flag(tmp_path):
    root = _surfaces(tmp_path)
    refused = _run_audit(root, ["--grid-m", "1e-06"])
    assert refused.returncode != 0
    assert "10nm" in (refused.stderr or "")
    allowed = _run_audit(root, ["--grid-m", "1e-06", "--benchmark", "--view", "front"])
    assert allowed.returncode == 0
    document = json.loads((root / "projection-front.json").read_text(encoding="utf-8"))
    assert document["benchmark"] is True and document["complete"] is True


def test_audit_cli_cache_hit_matches_uncached(tmp_path):
    root = _surfaces(tmp_path)
    cache_root = tmp_path / "shared-cache"
    first = _run_audit(root, ["--grid-m", "0", "--cache-root", str(cache_root)])
    assert first.returncode == 0
    before = json.loads((root / "projections.json").read_text(encoding="utf-8"))
    assert all(record["cache"]["status"] == "miss"
               for record in before["cache"].values())
    second = _run_audit(root, ["--grid-m", "0", "--cache-root", str(cache_root)])
    assert second.returncode == 0
    after = json.loads((root / "projections.json").read_text(encoding="utf-8"))
    assert all(record["cache"]["status"] == "hit" for record in after["cache"].values())
    for view in REQUIRED_VIEWS:
        assert after["views"][view]["source_m2"] == pytest.approx(before["views"][view]["source_m2"])
        assert after["views"][view]["iou"] == pytest.approx(before["views"][view]["iou"])


def test_audit_cli_parallel_views_match_serial(tmp_path):
    serial_root = _surfaces(tmp_path / "serial")
    parallel_root = _surfaces(tmp_path / "parallel")
    assert _run_audit(serial_root, ["--grid-m", "0", "--no-projection-cache"]).returncode == 0
    serial = json.loads((serial_root / "projections.json").read_text(encoding="utf-8"))
    jobs = []
    for view in REQUIRED_VIEWS:
        jobs.append(subprocess.Popen(
            [sys.executable, str(AUDIT), "--root", str(parallel_root), "--view", view,
             "--grid-m", "0", "--no-projection-cache"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace"))
    assert all(process.wait() == 0 for process in jobs)
    rows = {}
    for view in REQUIRED_VIEWS:
        document = json.loads(
            (parallel_root / ("projection-" + view + ".json")).read_text(encoding="utf-8"))
        assert document["complete"] is True and set(document["views"]) == {view}
        rows[view] = document["views"][view]
    merged = merge_views(rows)
    for view in REQUIRED_VIEWS:
        assert merged["views"][view]["source_m2"] == pytest.approx(serial["views"][view]["source_m2"])
        assert merged["views"][view]["candidate_m2"] == pytest.approx(serial["views"][view]["candidate_m2"])
        assert merged["views"][view]["iou"] == pytest.approx(serial["views"][view]["iou"])
    (parallel_root / CANONICAL_NAME).write_text(json.dumps(merged), encoding="utf-8")
    document, source = load_authoritative_projections(parallel_root)
    assert source == CANONICAL_NAME
