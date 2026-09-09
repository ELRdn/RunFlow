"""Reproducible 32-pose Phase 1 CFD execution lane.

The cycle lane deliberately keeps the Phase 1.0/provisional lane separate:
each frame gets a fresh 0.9 mm full-body surface and a fresh OpenFOAM case,
while the numerical family, physics, and convergence contract remain common.
Formal coefficients are emitted only after the existing force, residual,
flux, and normal-completion gates pass.  Geometry fidelity and scientific
approval stay independent fields throughout.
"""

from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from . import cfd
from .cfd_guard import directory_bytes
from .core import digest, file_hash, read, write
from .cfd_metrics import assess, coefficients, read_forces, read_residuals
from .contracts import PARTS, validate as validate_phase0


REPO = Path(__file__).resolve().parents[2]
BLENDER = cfd.BLENDER
CYCLE_VERSION = "phase1-cycle-1"
CYCLE_PROTOCOL_ID = "RF-CFD-P1-CYCLE-001"
CYCLE_FAMILY_VERSION = "phase1-cycle-family-1"
VOXEL_M = 0.0009
FRAME_COUNT = 32
FIXED_PARTS = set(PARTS)
TOOL_FILES = (
    "configs/cfd.phase1-provisional.json",
    "integrations/blender/prepare_cycle_surface.py",
    "scripts/cfd_surface_io.py",
    "scripts/cfd_worker.py",
    "scripts/cfd_report.py",
    "src/runflow/cfd.py",
    "src/runflow/cfd_case.py",
    "src/runflow/cfd_cycle.py",
    "src/runflow/cfd_guard.py",
    "src/runflow/cfd_metrics.py",
    "src/runflow/cfd_vtk.py",
    "src/runflow/core.py",
    "src/runflow/geometry.py",
    "src/runflow/gait_cycle.py",
    "uv.lock",
)


def _portable_relative(value):
    value = str(value)
    path = Path(value)
    if "\\" in value or path.is_absolute() or ":" in value or ".." in path.parts:
        raise ValueError("Cycle asset path must be relative and portable: " + value)
    return path


def _frame_path(manifest_path, source_root, relative):
    rel = _portable_relative(relative)
    candidates = []
    for base in (Path(source_root), Path(manifest_path).parent, Path(manifest_path).parent.parent):
        path = (base / rel).resolve()
        if path.is_file() and path not in candidates:
            candidates.append(path)
    if len(candidates) != 1:
        raise ValueError("Cycle snapshot is missing or ambiguous: " + str(relative))
    return candidates[0]


def _repeat_path(source_path, relative):
    rel = str(relative).replace("/", "\\")
    if rel.lower().startswith("unity-a\\"):
        rel = "unity-b\\" + rel[len("unity-a\\"):]
    else:
        return None
    candidate = Path(source_path).parents[1] / Path(rel)
    return candidate.resolve()


def validate_cycle_manifest(manifest_path, source_root=None):
    """Validate the finalized 32-frame intake and return resolved frame rows."""
    manifest_path = Path(manifest_path).resolve()
    if source_root is None:
        source_root = manifest_path.parent.parent
    source_root = Path(source_root).resolve()
    manifest = read(manifest_path)
    if manifest.get("execution_status") != "PASS":
        raise ValueError("Cycle intake manifest is not PASS")
    config = manifest.get("config")
    if not isinstance(config, dict) or digest(config) != manifest.get("config_sha256"):
        raise ValueError("Cycle intake manifest identity mismatch")
    if config.get("schema_version") != "phase1-cycle-input-1":
        raise ValueError("Wrong cycle intake schema")
    if (config.get("character_id"), config.get("costume_id")) != ("1006", "100602"):
        raise ValueError("Cycle intake target is not Oguri Cap Cinderella Gray")
    if config.get("endpoint_excluded") is not True or len(config.get("frames", [])) != FRAME_COUNT:
        raise ValueError("Exactly 32 endpoint-excluded cycle frames are required")
    frames = sorted(config["frames"], key=lambda row: row.get("index", -1))
    if [row.get("index") for row in frames] != list(range(FRAME_COUNT)):
        raise ValueError("Cycle frame indexes must be exactly 0..31")
    previous_time = None
    resolved = []
    for row in frames:
        relative = row.get("snapshot")
        path = _frame_path(manifest_path, source_root, relative)
        if file_hash(path) != row.get("sha256"):
            raise ValueError("Cycle source snapshot hash mismatch at frame " + str(row["index"]))
        snapshot = read(path)
        validate_phase0("snapshot", snapshot)
        if set(snapshot.get("parts", [])) != FIXED_PARTS:
            raise ValueError("Required source parts missing at frame " + str(row["index"]))
        frame_time = float(row.get("time_s"))
        if not math.isfinite(frame_time) or not math.isclose(snapshot["time_s"], frame_time, abs_tol=1e-9, rel_tol=0):
            raise ValueError("Cycle frame time mismatch at frame " + str(row["index"]))
        if previous_time is not None and not frame_time > previous_time:
            raise ValueError("Cycle frame times must increase")
        previous_time = frame_time
        repeat = _repeat_path(path, relative)
        repeated = None
        if repeat is not None:
            if not repeat.is_file():
                raise ValueError("Repeated cycle snapshot is missing at frame " + str(row["index"]))
            repeated = file_hash(repeat)
            if repeated != row.get("repeat_sha256"):
                raise ValueError("Repeated cycle snapshot hash mismatch at frame " + str(row["index"]))
        resolved.append(dict(index=int(row["index"]), phase_fraction=float(row["phase_fraction"]),
                             time_s=frame_time, weight=float(row["weight"]), relative_path=str(relative),
                             path=path, sha256=row["sha256"], repeat_sha256=row.get("repeat_sha256"),
                             repeat_path=repeat, repeat_verified=repeated is not None))
    if not math.isclose(sum(row["weight"] for row in resolved), 1.0, abs_tol=1e-12, rel_tol=0):
        raise ValueError("Cycle frame weights must sum to one")
    return dict(path=manifest_path, source_root=source_root, manifest=manifest,
                manifest_sha256=file_hash(manifest_path), frames=resolved)


def cycle_family(protocol):
    """Hash only common physics/numerics, excluding frame and source identity."""
    value = deepcopy(protocol)
    value["frame"] = None
    value.pop("cycle", None)
    if isinstance(value.get("diagnostic_refinement"), dict):
        value["diagnostic_refinement"]["source_snapshot_sha256"] = None
    return digest(dict(schema_version=CYCLE_FAMILY_VERSION, protocol=value))


def build_protocol(frame, source_sha256, frame_time_s, request, surface_override=None):
    base = read(REPO / "configs/cfd.phase1-provisional.json")
    protocol = deepcopy(base)
    protocol.update(schema_version=CYCLE_VERSION, protocol_id=CYCLE_PROTOCOL_ID, frame=int(frame))
    protocol["geometry"] = dict(
        mode="voxel_remesh_0.9mm_fullbody",
        local_weld_m=1e-6,
        voxel_m=VOXEL_M,
        min_triangle_area_m2=1e-16,
        voxel_remesh_passes=1,
        normal_recalculation="post_voxel_bmesh_recalc_face_normals_v1",
        fidelity_gate="USER_ACCEPTED_PROVISIONAL_FULLBODY",
    )
    # The Foundation motorBikeSteady run initializes the velocity potential
    # before the steady incompressible solver. Keep this as an explicit,
    # hashed protocol input so a retry is reproducible and distinguishable
    # from the first uniform-field attempt.
    protocol["solver_initialization"] = dict(
        method="potentialFoam",
        # Foundation 14's -writePhi output is a volScalarField named phi,
        # which collides with incompressibleFluid's surface flux field. The
        # motorBikeSteady workflow needs only the initialized U field here.
        write_phi=False,
        write_pressure=False,
    )
    if surface_override:
        protocol["geometry"].update(
            mode="saved_local_repair_candidate",
            voxel_m=float(surface_override.get("voxel_m", VOXEL_M)),
            voxel_remesh_passes=0,
            normal_recalculation="external_candidate_preserved",
            fidelity_gate="FOUNDATION_AND_SHAPE_AUDIT_PASS",
            repair_method=str(surface_override["method"]),
            repair_max_weld_m=float(surface_override["max_weld_m"]),
        )
    protocol["diagnostic_refinement"] = dict(
        reason_id="oguri_coat_tip_flow_reversal_001",
        source_snapshot_sha256=source_sha256,
        box_min_m=[-0.2, -0.37, 0.3],
        box_max_m=[0.1, -0.17, 0.5],
        level=6,
    )
    phase_period = float(request["source_period_s"])
    phase = (float(request["clip_start_phase_s"]) + int(frame) * phase_period / FRAME_COUNT) % phase_period
    family = cycle_family(protocol)
    protocol["cycle"] = dict(
        phase_index=int(frame), phase_fraction=int(frame) / FRAME_COUNT,
        frame_time_s=float(frame_time_s), clip_phase_s=phase,
        source_snapshot_sha256=source_sha256,
        comparison_family_sha256=family,
        endpoint_excluded=True,
    )
    if surface_override:
        protocol["cycle"].update(
            surface_repair_candidate_sha256=surface_override["candidate_sha256"],
            surface_repair_sha256=surface_override["repair_sha256"],
            shape_audit_sha256=surface_override.get("shape_audit_sha256"),
        )
    return protocol


def _state(root, **updates):
    value = read(root / "state.json")
    value.update(updates, updated_epoch=time.time())
    write(root / "state.json", value)
    return value


def _write_result(root, status, stage, reason, evidence=None, coeff=None):
    evidence = evidence or {}
    protocol = read(root / "protocol.json") if (root / "protocol.json").exists() else {}
    experiment = read(root / "experiment.json") if (root / "experiment.json").exists() else {}
    config = experiment.get("config", {})
    identity = experiment.get("experiment_id")
    if not identity:
        identity = "rf-p1c-unprepared-" + digest(dict(protocol=protocol, stage=stage, reason=reason))
    value = dict(
        schema_version=CYCLE_VERSION,
        experiment_id=identity,
        execution_status=status,
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        ranking_eligible=False,
        drag_N=None,
        Cd=None,
        CdA_m2=None,
        reason=str(reason),
        stage=stage,
        phase_index=protocol.get("frame"),
        phase_time_s=config.get("frame_time_s", protocol.get("cycle", {}).get("frame_time_s")),
        clip_phase_s=config.get("clip_phase_s", protocol.get("cycle", {}).get("clip_phase_s")),
        source_area_m2=config.get("source_area_m2"),
        candidate_area_m2=config.get("candidate_area_m2"),
        comparison_family_sha256=config.get("comparison_family_sha256", protocol.get("cycle", {}).get("comparison_family_sha256")),
        evidence=evidence,
    )
    if status == "PASS" and coeff:
        value.update(coeff)
    write(root / "result.json", value)
    if (root / "state.json").exists():
        _state(root, status=status, stage=stage)
    return value


def _record_tools(root, upstream=None):
    pins = {}
    for relative in TOOL_FILES:
        path = REPO / relative
        if not path.is_file():
            raise ValueError("Missing pinned cycle processing source: " + relative)
        pins["repo:" + relative] = file_hash(path)
        archived = root / "tool-sources" / relative
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, archived)
    if upstream:
        pins.update({"upstream:" + key: value for key, value in upstream.get("hashes", {}).items()})
        pins.update({"binary:" + key: value["sha256"] for key, value in upstream.get("binaries", {}).items()})
    return pins


def _case_hashes(case):
    return {"case:" + path.relative_to(case).as_posix(): file_hash(path)
            for path in sorted(case.rglob("*")) if path.is_file()}


def verify_prepared(root):
    root = cfd.private(root)
    state = read(root / "state.json")
    if state.get("status") != "PREPARED":
        raise ValueError("Cycle frame is not PREPARED")
    experiment = read(root / "experiment.json")
    config = experiment.get("config")
    if not isinstance(config, dict) or digest(config) != experiment.get("config_sha256"):
        raise ValueError("Cycle experiment identity mismatch")
    if experiment.get("experiment_id") != "rf-p1c-" + experiment["config_sha256"]:
        raise ValueError("Cycle experiment prefix mismatch")
    if read(root / "protocol.json") != config.get("protocol"):
        raise ValueError("Cycle protocol changed after preparation")
    for name, expected in (("source.snapshot.json", config.get("source_snapshot_sha256")),
                           ("source-manifest.json", config.get("source_manifest_sha256")),
                           ("geometry/candidate.obj", config.get("surface_sha256"))):
        if not expected or file_hash(root / name) != expected:
            raise ValueError("Cycle prepared input changed: " + name)
    geometry = read(root / "geometry/geometry.json")
    if geometry.get("candidate_sha256") != config.get("surface_sha256") or not geometry.get("candidate_topology", {}).get("closed"):
        raise ValueError("Cycle geometry topology gate is not closed")
    surface = read(root / "surface-worker.json")
    if surface.get("execution_status") != "PASS":
        raise ValueError("Foundation surface gate is not PASS")
    tools = config.get("tool_hashes", {})
    for key, expected in tools.items():
        if key.startswith("repo:"):
            path = root / "tool-sources" / key[5:]
            if file_hash(path) != expected:
                raise ValueError("Archived cycle source changed: " + key)
        elif key.startswith("case:"):
            if file_hash(root / "case" / key[5:]) != expected:
                raise ValueError("Cycle case input changed: " + key)
        elif key.startswith("upstream:"):
            if read(root / "upstream.json")["hashes"].get(key[9:]) != expected:
                raise ValueError("Upstream cycle reference changed: " + key)
        elif key.startswith("binary:"):
            if read(root / "upstream.json")["binaries"].get(key[7:], {}).get("sha256") != expected:
                raise ValueError("OpenFOAM binary changed: " + key)
    for name, expected in read(root / "runtime-evidence-hashes.json").items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or file_hash(path) != expected:
            raise ValueError("Cycle runtime evidence changed: " + name)
    return experiment


def _failure_reason(root, stage, default):
    worker_path = root / (stage + "-worker.json")
    if worker_path.exists():
        value = read(worker_path)
        if value.get("error"):
            return str(value["error"])
    executions = sorted(root.glob(stage + "*.execution.json"))
    for path in reversed(executions):
        value = read(path)
        if value.get("reason"):
            return str(value["reason"])
        if value.get("returncode") not in (None, 0):
            return "command failed; inspect " + stage + " logs"
    return default


def _status_for_reason(reason):
    lowered = str(reason).lower()
    return "TIMEOUT" if any(word in lowered for word in ("timeout", "memory limit", "output size limit", "disk reserve")) else "FAIL"


def _collect_histories(root):
    evidence = {}
    warnings = []
    files = list((root / "case/postProcessing/forces").rglob("forces.dat")) if (root / "case").exists() else []
    if len(files) == 1:
        try:
            values = read_forces(files[0]); write(root / "force-history.json", values); evidence["force_history_rows"] = len(values)
        except (OSError, ValueError) as exc:
            warnings.append("Force history: " + str(exc))
    elif files:
        warnings.append("Force history is ambiguous")
    if (root / "foamRun.log").exists():
        try:
            values = read_residuals(root / "foamRun.log"); write(root / "residual-history.json", values); evidence["residual_iterations"] = len(values)
        except (OSError, ValueError) as exc:
            warnings.append("Residual history: " + str(exc))
    if (root / "flux-history.json").exists():
        try:
            evidence["flux_rows"] = len(read(root / "flux-history.json"))
        except (OSError, ValueError):
            warnings.append("Flux history is unreadable")
    evidence["warnings"] = warnings
    return evidence


def _surface_override_info(surface_override, shape_audit_root=None, expected_source_sha256=None):
    """Validate a private repair candidate and return portable hash evidence."""
    if surface_override is None:
        return None, None
    candidate = cfd.private(surface_override)
    if not candidate.is_file() or candidate.name != "candidate.obj":
        raise ValueError("External cycle surface must be a private candidate.obj")
    source_root = candidate.parent
    geometry_path = source_root / "geometry.json"
    repair_path = source_root / "repair.json"
    if not geometry_path.is_file() or not repair_path.is_file():
        raise ValueError("External cycle surface requires geometry.json and repair.json")
    geometry = read(geometry_path)
    repair = read(repair_path)
    candidate_sha = file_hash(candidate)
    if geometry.get("candidate_sha256") != candidate_sha:
        raise ValueError("External cycle candidate hash does not match geometry.json")
    if not geometry.get("candidate_topology", {}).get("closed"):
        raise ValueError("External cycle candidate is not marked closed")
    if repair.get("status") != "PASS":
        raise ValueError("External cycle repair record is not PASS")
    if repair.get("output_counts") != geometry.get("candidate_counts"):
        raise ValueError("External cycle repair and geometry counts differ")
    max_weld = repair.get("max_weld_m", 0.0)
    if not isinstance(max_weld, (int, float)) or not math.isfinite(float(max_weld)) or not 0.0 <= float(max_weld) <= 0.002:
        raise ValueError("External cycle repair weld limit is outside the authorized range")
    if expected_source_sha256 is not None and geometry.get("source_sha256") != expected_source_sha256:
        raise ValueError("External cycle candidate belongs to a different cycle frame")
    audit_hashes = {}
    if shape_audit_root is not None:
        audit_root = cfd.private(shape_audit_root)
        for name in (
            "request.json", "source-to-candidate.json", "candidate-to-source.json",
            "projections.json", "views.json", "sections.json",
        ):
            path = audit_root / name
            if not path.is_file():
                raise ValueError("Shape audit evidence is missing: " + name)
            audit_hashes[name] = file_hash(path)
        audit_request = read(audit_root / "request.json")
        if audit_request.get("schema_version") != "phase1-cycle-shape-audit-1":
            raise ValueError("Wrong cycle shape-audit schema")
        source_entry = audit_request.get("source", {})
        candidate_entry = audit_request.get("candidate", {})
        if candidate_entry.get("sha256") != candidate_sha:
            raise ValueError("Shape audit candidate does not match external cycle candidate")
        audit_source = Path(source_entry.get("path", "")).resolve()
        if not audit_source.is_file() or file_hash(audit_source) != source_entry.get("sha256"):
            raise ValueError("Shape audit source hash is not reproducible")
        distance_rows = []
        for name in ("source-to-candidate.json", "candidate-to-source.json"):
            value = read(audit_root / name)
            if value.get("complete") is not True or float(value.get("global_max_upper_m", float("inf"))) > 0.002:
                raise ValueError("Shape audit distance gate did not pass: " + name)
            distance_rows.append(value)
        projections = read(audit_root / "projections.json")
        views = read(audit_root / "views.json")
        sections = read(audit_root / "sections.json")
        if projections.get("complete") is not True or any(
                float(value.get("relative_change_abs", float("inf"))) > 0.01
                for value in projections.get("views", {}).values()):
            raise ValueError("Shape audit projection gate did not pass")
        if views.get("complete") is not True or sections.get("complete") is not True:
            raise ValueError("Shape audit visual/section stages are incomplete")
    info = dict(
        candidate_sha256=candidate_sha,
        repair_sha256=file_hash(repair_path),
        geometry_sha256=file_hash(geometry_path),
        method=str(repair.get("method")),
        max_weld_m=float(max_weld),
        voxel_m=float(geometry.get("voxel_m", VOXEL_M)),
        input_geometry_sha256=repair.get("input_geometry_sha256"),
        shape_audit_sha256=digest(audit_hashes) if audit_hashes else None,
        shape_audit_files=audit_hashes,
        candidate_counts=geometry.get("candidate_counts"),
        candidate_topology=geometry.get("candidate_topology"),
    )
    return info, dict(geometry=geometry, repair=repair, candidate=candidate)


def prepare_frame(request, frame_record, campaign_root, *, distro="Ubuntu", surface_override=None, shape_audit_root=None):
    """Prepare one fresh frame and stop before the solver."""
    campaign_root = cfd.private(campaign_root)
    frame = int(frame_record["index"])
    label = f"frame-{frame:02d}-001"
    root = campaign_root / label
    if root.exists():
        raise ValueError("Fresh cycle frame output required: " + label)
    source = Path(frame_record["path"]).resolve()
    manifest_path = Path(request["manifest_path"]).resolve()
    source_manifest_sha = file_hash(manifest_path)
    override, override_records = _surface_override_info(
        surface_override, shape_audit_root, expected_source_sha256=frame_record["sha256"]
    )
    protocol = build_protocol(frame, frame_record["sha256"], frame_record["time_s"], request, override)
    started_epoch = time.time()
    root.mkdir(parents=True, exist_ok=False)
    write(root / "protocol.json", protocol)
    write(root / "state.json", dict(started_epoch=started_epoch,
                                     started_utc=datetime.fromtimestamp(started_epoch, timezone.utc).isoformat(),
                                     status="PREPARING", stage="geometry", distro=distro, phase_index=frame))
    evidence = {}
    try:
        shutil.copyfile(source, root / "source.snapshot.json")
        shutil.copyfile(manifest_path, root / "source-manifest.json")
        write(root / "source-frame.json", dict(**{key: value for key, value in frame_record.items() if key not in ("path", "repeat_path")},
                                                source_runtime_path=str(source)))
        geometry_started = time.monotonic()
        if override:
            (root / "geometry").mkdir(parents=True, exist_ok=False)
            shutil.copyfile(override_records["candidate"], root / "geometry/candidate.obj")
            geometry_record = deepcopy(override_records["geometry"])
            geometry_record["candidate_sha256"] = file_hash(root / "geometry/candidate.obj")
            geometry_record["surface_repair_provenance"] = dict(
                repair_sha256=override["repair_sha256"],
                geometry_sha256=override["geometry_sha256"],
                shape_audit_sha256=override["shape_audit_sha256"],
            )
            write(root / "geometry/geometry.json", geometry_record)
            write(root / "repair-provenance.json", dict(
                schema_version="phase1-cycle-repair-provenance-1",
                candidate_sha256=override["candidate_sha256"],
                repair_sha256=override["repair_sha256"],
                geometry_sha256=override["geometry_sha256"],
                input_geometry_sha256=override["input_geometry_sha256"],
                method=override["method"], max_weld_m=override["max_weld_m"],
                shape_audit_sha256=override["shape_audit_sha256"],
                shape_audit_files=override["shape_audit_files"],
            ))
            geometry_request = dict(
                mode="external_repaired_candidate",
                source_sha256=frame_record["sha256"],
                candidate_sha256=override["candidate_sha256"],
                output="geometry",
                geometry=protocol["geometry"],
            )
            write(root / "geometry-request.json", geometry_request)
            evidence["blender"] = dict(mode="external_repaired_candidate", elapsed_s=0.0,
                                        candidate_sha256=override["candidate_sha256"])
        else:
            geometry_request = dict(source=str(root / "source.snapshot.json"),
                                    source_sha256=frame_record["sha256"], output=str(root / "geometry"),
                                    timeout_s=cfd.remaining(root, "geometry", geometry_started),
                                    geometry=dict(weld_m=1e-6, voxel_m=VOXEL_M))
            write(root / "geometry-request.json", geometry_request)
            command = [str(BLENDER), "--background", "--factory-startup", "--threads", "20",
                       "--python-exit-code", "2", "--python",
                       str(REPO / "integrations/blender/prepare_cycle_surface.py"), "--",
                       "--request", str(root / "geometry-request.json")]
            evidence["blender"] = cfd.guarded(root, command, "blender.log",
                                                cfd.remaining(root, "geometry", geometry_started))
        geometry = read(root / "geometry/geometry.json")
        evidence["geometry"] = dict(voxel_m=geometry.get("voxel_m"), candidate_sha256=geometry.get("candidate_sha256"),
                                     candidate_topology=geometry.get("candidate_topology"),
                                     candidate_counts=geometry.get("candidate_counts"))
        if not geometry.get("candidate_topology", {}).get("closed"):
            return _write_result(root, "BLOCKED", "geometry", "Generated full-body surface is not closed", evidence)
        evidence["reference"] = cfd.worker(root, "reference", cfd.remaining(root, "geometry", geometry_started), distro)
        evidence["surface"] = cfd.worker(root, "surface", cfd.remaining(root, "geometry", geometry_started), distro)
        if override and evidence["surface"].get("execution_status") == "PASS":
            geometry = read(root / "geometry/geometry.json")
            geometry["candidate_topology"]["self_intersection_verified"] = True
            geometry["foundation_surface_check"] = dict(execution_status="PASS", checker="OpenFOAM Foundation 14 surfaceCheck")
            write(root / "geometry/geometry.json", geometry)
        from .geometry import area
        source_snapshot = read(root / "source.snapshot.json")
        source_area = area(source_snapshot)
        if not math.isfinite(source_area) or source_area <= 0:
            raise ValueError("Source projected area is not finite and positive")
        case = root / "case"
        (case / "constant/geometry").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "geometry/candidate.obj", case / "constant/geometry/oguri.obj")
        upstream = read(root / "upstream.json")
        from .cfd_case import build
        design = build(case, source_snapshot, protocol, upstream,
                       numerics="standard-simple-upwind-damped-nonorth",
                       wall_treatment="reference-switching")
        write(root / "case-design.json", design)
        tools = _record_tools(root, upstream)
        tools.update(_case_hashes(case))
        config = dict(
            source_snapshot_sha256=file_hash(root / "source.snapshot.json"),
            source_manifest_sha256=file_hash(root / "source-manifest.json"),
            surface_sha256=file_hash(root / "geometry/candidate.obj"),
            geometry_record_sha256=file_hash(root / "geometry/geometry.json"),
            frame_time_s=float(frame_record["time_s"]),
            clip_phase_s=protocol["cycle"]["clip_phase_s"],
            phase_index=frame,
            source_area_m2=source_area,
            candidate_area_m2=None,
            candidate_area_status="NOT_MEASURED_CYCLE_BATCH",
            source_bbox=design["source_bbox"],
            protocol=protocol,
            comparison_family_sha256=protocol["cycle"]["comparison_family_sha256"],
            surface_repair_sha256=override["repair_sha256"] if override else None,
            shape_audit_sha256=override["shape_audit_sha256"] if override else None,
            tool_hashes=tools,
            cycle_manifest_sha256=source_manifest_sha,
            cycle_manifest_config_sha256=read(root / "source-manifest.json")["config_sha256"],
        )
        config_sha = digest(config)
        experiment = dict(schema_version=CYCLE_VERSION, experiment_id="rf-p1c-" + config_sha,
                          config_sha256=config_sha, config=config)
        write(root / "experiment.json", experiment)
        runtime_names = ["source-frame.json", "geometry-request.json", "geometry/geometry.json",
                         "surface-worker.json", "surface-io.json", "upstream.json", "case-design.json"]
        if override:
            runtime_names.append("repair-provenance.json")
        write(root / "runtime-evidence-hashes.json", {name: file_hash(root / name) for name in runtime_names})
        evidence.update(source_area_m2=source_area, candidate_area_m2=None,
                        candidate_area_status="NOT_MEASURED_CYCLE_BATCH", comparison_family_sha256=config["comparison_family_sha256"])
        _state(root, status="PREPARED", stage="geometry")
        return _write_result(root, "PREPARED", "geometry", "Full-body 0.9 mm surface and OpenFOAM case prepared", evidence)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        reason = str(exc)
        return _write_result(root, _status_for_reason(reason), "geometry", reason, evidence)


def run_frame(root, *, distro=None):
    """Run a prepared frame through mesh, solver, fields, and report."""
    root = cfd.private(root)
    exp = verify_prepared(root)
    protocol = exp["config"]["protocol"]
    state = read(root / "state.json")
    distro = distro or state.get("distro", "Ubuntu")
    evidence = {}
    _state(root, status="RUNNING", stage="mesh")
    mesh_started = time.monotonic()
    try:
        evidence["mesh"] = cfd.worker(root, "mesh", cfd.remaining(root, "mesh", mesh_started), distro)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        evidence["mesh_failure"] = _failure_reason(root, "mesh", str(exc))
        return _write_result(root, _status_for_reason(evidence["mesh_failure"]), "mesh", evidence["mesh_failure"], evidence)
    _state(root, status="RUNNING", stage="solver")
    solver_started = time.monotonic()
    solver_error = None
    try:
        evidence["solver"] = cfd.worker(root, "solver", cfd.remaining(root, "solver", solver_started), distro)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        solver_error = _failure_reason(root, "solver", str(exc))
        evidence["solver_failure"] = solver_error
    history = _collect_histories(root)
    evidence["history"] = history
    forces = residuals = flux = None
    try:
        force_files = list((root / "case/postProcessing/forces").rglob("forces.dat"))
        if len(force_files) != 1:
            raise ValueError("Force history missing or ambiguous")
        forces = read_forces(force_files[0])
        residuals = read_residuals(root / "foamRun.log")
        flux = read(root / "flux-history.json")
        convergence = assess(forces, residuals, flux, protocol)
        evidence["convergence"] = convergence
        write(root / "force-history.json", forces)
        write(root / "residual-history.json", residuals)
    except (OSError, ValueError, RuntimeError) as exc:
        evidence["diagnostic_parse_error"] = str(exc)
        convergence = dict(converged=False, reasons=[str(exc)], window_mean_drag_N=None, metrics={})
    normal_completion = False
    if (root / "foamRun.log").exists():
        with (root / "foamRun.log").open("rb") as stream:
            stream.seek(max(0, stream.seek(0, 2) - 65536))
            tail = stream.read().decode("utf-8", "replace")
        normal_completion = bool(re.search(r"(?m)^\s*End\s*$", tail))
    evidence["normal_solver_completion"] = normal_completion
    if solver_error:
        status = _status_for_reason(solver_error)
        return _write_result(root, status, "solver", solver_error, evidence)
    if not normal_completion:
        return _write_result(root, "FAIL", "solver", "Solver normal completion marker is missing", evidence)
    if not convergence.get("converged"):
        reason = "; ".join(convergence.get("reasons", [])) or "Convergence gates did not pass"
        return _write_result(root, "NOT_CONVERGED", "solver", reason, evidence)
    try:
        coeff = coefficients(convergence["window_mean_drag_N"], protocol["air_density_kg_m3"],
                             protocol["speed_m_s"], exp["config"]["source_area_m2"])
        _state(root, status="RUNNING", stage="report")
        cfd.start_report(root)
        report_started = time.monotonic()
        evidence["fields"] = cfd.worker(root, "fields", cfd.remaining(root, "report", report_started), distro)
        evidence["report"] = cfd.guarded(root, [sys.executable, str(REPO / "scripts/cfd_report.py"),
                                                 "--root", str(root)], "report.log",
                                           cfd.remaining(root, "report", report_started))
        _state(root, completed_epoch=time.time(), stage="report")
        return _write_result(root, "PASS", "report", "All cycle solver and reporting gates passed", evidence, coeff)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        reason = str(exc)
        return _write_result(root, _status_for_reason(reason), "report", reason, evidence)


def execute_frame(request, frame_record, campaign_root, *, distro="Ubuntu", surface_override=None, shape_audit_root=None):
    """Prepare and, only when prepared, execute one frame exactly once."""
    prepared = prepare_frame(request, frame_record, campaign_root, distro=distro,
                             surface_override=surface_override, shape_audit_root=shape_audit_root)
    root = Path(campaign_root).resolve() / f"frame-{int(frame_record['index']):02d}-001"
    if prepared["execution_status"] != "PREPARED":
        return prepared
    return run_frame(root, distro=distro)
