"""Union disconnected components of one cycle surface with pinned Manifold.

The earlier self-union probe operated on the complete Manifold as one operand.
This trial explicitly decomposes that operand first, then asks the Boolean
backend to add the components.  It is diagnostic and never overwrites its
input.
"""

import argparse
from pathlib import Path
import json
import sys
import time

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from repair_cycle_candidate import _validate_arrays, _write_obj
from repair_trial_support import manifold_backend
from runflow.cfd import private
from runflow.core import file_hash, read, write
from runflow.shape_fullbody import finish_cache


METHOD = "manifold_decompose_batch_add_v1"
BACKEND_COMMIT = "11235e6b8ebea2dbed8aec4285685aafd3d95667"


def repair(native_root, output, tolerance=0.0, order="native", input_tolerance=0.0):
    native_root = Path(native_root).resolve()
    output = private(output)
    if output.exists():
        raise ValueError("Fresh component-union geometry output required")
    native_geometry = read(native_root / "geometry.json")
    vertices = np.load(native_root / "arrays/vertices.npy", mmap_mode="r")
    triangles = np.load(native_root / "arrays/triangles.npy", mmap_mode="r")
    _validate_arrays(vertices, triangles)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Manifold tolerance must be finite and nonnegative")
    if not np.isfinite(input_tolerance) or input_tolerance < 0:
        raise ValueError("Manifold input tolerance must be finite and nonnegative")
    if order not in {"native", "reverse", "small_first", "large_first"}:
        raise ValueError("Unsupported component order")
    method = METHOD if tolerance == 0 else METHOD + "_tolerance"
    if order != "native":
        method += "_order_" + order
    if input_tolerance:
        method += "_input_tolerance"
    input_hashes = {
        "native_geometry.json": file_hash(native_root / "geometry.json"),
        "native_candidate.obj": file_hash(native_root / "candidate.obj"),
        "native_arrays/vertices.npy": file_hash(native_root / "arrays/vertices.npy"),
        "native_arrays/triangles.npy": file_hash(native_root / "arrays/triangles.npy"),
        "repair_script": file_hash(Path(__file__)),
        "repair_support": file_hash(REPO / "scripts/repair_trial_support.py"),
    }
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        input_vertices = np.array(vertices, dtype=np.float64, order="C", copy=True)
        input_triangles = np.array(triangles, dtype=np.uint64, order="C", copy=True)
        manifold = manifold_backend(REPO)
        mesh = manifold.Mesh64(input_vertices, input_triangles, tolerance=float(input_tolerance))
        body = manifold.Manifold(mesh)
        if body.status() != manifold.Error.NoError or body.num_tri() == 0:
            raise ValueError("Manifold did not accept the native surface: " + str(body.status()))
        components = body.decompose()
        component_counts = [int(item.num_tri()) for item in components]
        print("MANIFOLD_COMPONENTS_DECOMPOSED", len(components), sum(component_counts), flush=True)
        if not components:
            raise ValueError("Manifold decomposition returned no components")
        if order == "reverse":
            components = list(reversed(components))
        elif order == "small_first":
            components = sorted(components, key=lambda item: item.num_tri())
        elif order == "large_first":
            components = sorted(components, key=lambda item: item.num_tri(), reverse=True)
        if tolerance:
            components = [component.set_tolerance(float(tolerance)) for component in components]
        joined = manifold.Manifold.batch_boolean(components, manifold.OpType.Add)
        status = str(joined.status())
        print("MANIFOLD_COMPONENT_BATCH_ADD_RESULT", status, joined.num_tri(), flush=True)
        if joined.status() != manifold.Error.NoError or joined.num_tri() == 0:
            raise ValueError("Manifold component batch union failed: " + status)
        exported = joined.to_mesh64()
        out_vertices = np.asarray(exported.vert_properties, dtype=np.float64)[:, :3]
        out_triangles = np.asarray(exported.tri_verts, dtype=np.int32)
        _validate_arrays(out_vertices, out_triangles)
        arrays = output / "arrays"
        arrays.mkdir(parents=True, exist_ok=False)
        np.save(arrays / "vertices.npy", out_vertices)
        np.save(arrays / "triangles.npy", out_triangles)
        cache = finish_cache(arrays, source_sha256=input_hashes["native_candidate.obj"], method=method)
        candidate = output / "candidate.obj"
        _write_obj(candidate, out_vertices, out_triangles)
        output_hashes = {
            "candidate.obj": file_hash(candidate),
            "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
            "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
        }
        repair = dict(
            schema_version="phase1-cycle-component-union-1",
            status="PASS",
            method=method,
            backend="manifold3d 3.5.2",
            backend_commit=BACKEND_COMMIT,
            input_hashes=input_hashes,
            output_hashes=output_hashes,
            input_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
            output_counts={"vertices": int(len(out_vertices)), "triangles": int(len(out_triangles))},
            component_count=len(components),
            component_triangle_counts=component_counts,
            component_order=order,
            input_tolerance_m=float(input_tolerance),
            imported_triangles=int(body.num_tri()),
            output_triangles=int(joined.num_tri()),
            volume_m3=float(joined.volume()),
            tolerance_m=float(joined.get_tolerance()),
            requested_tolerance_m=float(tolerance),
            whole_input=True,
            may_remove_internal_overlaps=True,
            may_change_external_surface=True,
            smoothing=False,
            part_deletion=False,
            external_shape_audit="PENDING",
            surface_check="PENDING_FOUNDATION_SURFACECHECK",
            scientific_status="UNVALIDATED_PHASE1_CYCLE",
            cache=cache,
            native_geometry_sha256=input_hashes["native_geometry.json"],
            elapsed_s=time.monotonic() - started,
        )
        write(output / "repair.json", repair)
        write(output / "geometry.json", dict(
            schema_version="phase1-cycle-geometry-component-union-1",
            repair_method=method,
            source_sha256=native_geometry.get("source_sha256"),
            native_geometry_sha256=input_hashes["native_geometry.json"],
            voxel_m=native_geometry.get("voxel_m"), whole_input=True,
            coordinate_system=native_geometry.get("coordinate_system"), unit=native_geometry.get("unit"),
            candidate_sha256=output_hashes["candidate.obj"], candidate_obj_bytes=candidate.stat().st_size,
            candidate_counts=repair["output_counts"], candidate_arrays=output_hashes,
            repair=repair, self_intersection_verified=False,
            scientific_status="UNVALIDATED_PHASE1_CYCLE", human_review=None,
        ))
        print("MANIFOLD_COMPONENT_BATCH_ADD_SAVED", json.dumps(repair["output_counts"]), flush=True)
        return repair
    except BaseException as exc:
        write(output / "repair-failure.json", dict(
            schema_version="phase1-cycle-component-union-1", status="FAIL", method=method,
            input_hashes=input_hashes, error=str(exc), elapsed_s=time.monotonic() - started))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.0)
    parser.add_argument("--order", choices=("native", "reverse", "small_first", "large_first"), default="native")
    parser.add_argument("--input-tolerance", type=float, default=0.0)
    args = parser.parse_args()
    repair(args.input, args.output, args.tolerance, args.order, args.input_tolerance)


if __name__ == "__main__":
    main()
