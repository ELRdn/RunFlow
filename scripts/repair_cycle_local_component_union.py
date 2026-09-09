"""Locally union Manifold components implicated by Foundation witness points.

The full native surface is accepted by Manifold as several closed components,
but a whole-body Boolean changes the external envelope.  This diagnostic
keeps the largest native component and only the components whose bounding box
contains selected Foundation self-intersection witnesses in one Boolean.
Every other component is exported unchanged and concatenated as a separate
closed component.  The result is still required to pass Foundation
surfaceCheck and the independent shape audit before it can be used by CFD.
"""

import argparse
import json
from pathlib import Path
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


METHOD = "manifold_local_component_union_v1"
BACKEND_COMMIT = "11235e6b8ebea2dbed8aec4285685aafd3d95667"


def point_file(path):
    points = []
    for line in Path(path).read_text(encoding="ascii").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] != "v" or len(fields) != 4:
            raise ValueError("Foundation point OBJ must contain only v x y z lines")
        point = np.asarray([float(x) for x in fields[1:]], dtype=np.float64)
        if not np.isfinite(point).all():
            raise ValueError("Foundation point OBJ contains nonfinite coordinates")
        points.append(point)
    if not points:
        raise ValueError("Foundation point OBJ is empty")
    return np.asarray(points, dtype=np.float64)


def bbox_tuple(component):
    box = tuple(float(x) for x in component.bounding_box())
    if len(box) != 6 or not np.isfinite(box).all():
        raise ValueError("Manifold component returned an invalid bounding box")
    low = np.asarray(box[:3], dtype=np.float64)
    high = np.asarray(box[3:], dtype=np.float64)
    if np.any(high < low):
        raise ValueError("Manifold component bounding box is inverted")
    return low, high


def mesh_arrays(mesh):
    vertices = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    triangles = np.asarray(mesh.tri_verts, dtype=np.int32)
    _validate_arrays(vertices, triangles)
    return vertices, triangles


def select_components(components, points, padding):
    records = []
    selected = set()
    for index, component in enumerate(components):
        low, high = bbox_tuple(component)
        hits = np.flatnonzero(
            np.all(points >= low[None, :] - padding, axis=1)
            & np.all(points <= high[None, :] + padding, axis=1)
        ).astype(int)
        if len(hits):
            selected.add(index)
        records.append(dict(
            id=int(index),
            triangles=int(component.num_tri()),
            vertices=int(component.num_vert()),
            bbox_m=[low.tolist(), high.tolist()],
            point_indices=hits.tolist(),
            selected=bool(len(hits)),
        ))
    if not selected:
        raise ValueError("No component bbox contains a Foundation witness")
    return records, sorted(selected)


def save_candidate(output, vertices, triangles, native_geometry, input_hashes,
                   component_records, selected_ids, point_indices, padding, elapsed,
                   method, requested_tolerance, joined_tolerance, operation):
    arrays = output / "arrays"
    arrays.mkdir(parents=True, exist_ok=False)
    np.save(arrays / "vertices.npy", vertices)
    np.save(arrays / "triangles.npy", triangles)
    cache = finish_cache(
        arrays,
        source_sha256=input_hashes["native_candidate.obj"],
        method=method,
    )
    candidate = output / "candidate.obj"
    _write_obj(candidate, vertices, triangles)
    output_hashes = {
        "candidate.obj": file_hash(candidate),
        "arrays/vertices.npy": file_hash(arrays / "vertices.npy"),
        "arrays/triangles.npy": file_hash(arrays / "triangles.npy"),
    }
    selected_triangles = sum(component_records[i]["triangles"] for i in selected_ids)
    record = dict(
        schema_version="phase1-cycle-local-component-union-1",
        status="PASS",
        method=method,
        backend="manifold3d 3.5.2",
        backend_commit=BACKEND_COMMIT,
        input_hashes=input_hashes,
        output_hashes=output_hashes,
        input_counts=native_geometry.get("candidate_counts"),
        output_counts={"vertices": int(len(vertices)), "triangles": int(len(triangles))},
        component_count=len(component_records),
        selected_component_ids=selected_ids,
        selected_component_count=len(selected_ids),
        selected_input_triangles=int(selected_triangles),
        untouched_component_count=len(component_records) - len(selected_ids),
        witness_point_indices=point_indices,
        bbox_padding_m=float(padding),
        requested_tolerance_m=float(requested_tolerance),
        joined_tolerance_m=float(joined_tolerance),
        operation=operation,
        component_records=component_records,
        whole_input=True,
        unchanged_unselected_components=True,
        may_remove_internal_overlaps_in_selected_components=True,
        may_change_external_surface_in_selected_components=True,
        smoothing=False,
        hole_filling=False,
        part_deletion=False,
        external_shape_audit="PENDING",
        surface_check="PENDING_FOUNDATION_SURFACECHECK",
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        cache=cache,
        elapsed_s=float(elapsed),
    )
    write(output / "repair.json", record)
    write(output / "geometry.json", dict(
        schema_version="phase1-cycle-geometry-local-component-union-1",
        repair_method=method,
        source_sha256=native_geometry.get("source_sha256"),
        native_geometry_sha256=input_hashes["native_geometry.json"],
        voxel_m=native_geometry.get("voxel_m"),
        whole_input=True,
        coordinate_system=native_geometry.get("coordinate_system"),
        unit=native_geometry.get("unit"),
        candidate_sha256=output_hashes["candidate.obj"],
        candidate_obj_bytes=candidate.stat().st_size,
        candidate_counts=record["output_counts"],
        candidate_arrays=output_hashes,
        candidate_topology=dict(
            closed=True,
            self_intersection_verified=False,
            note="Selected components are Boolean-unioned; untouched components retain their native triangles.",
        ),
        repair=record,
        self_intersection_verified=False,
        scientific_status="UNVALIDATED_PHASE1_CYCLE",
        human_review=None,
    ))
    write(output / "component-selection.json", dict(
        complete=True,
        method=method,
        witness_point_indices=point_indices,
        bbox_padding_m=float(padding),
        selected_component_ids=selected_ids,
        components=component_records,
    ))
    return record


def repair(native_root, points_path, output, padding=1e-6, point_indices=None,
           tolerance=0.0, self_union=False):
    native_root = Path(native_root).resolve()
    output = private(output)
    if output.exists():
        raise ValueError("Fresh local component-union output required")
    if padding < 0 or not np.isfinite(padding):
        raise ValueError("BBox padding must be finite and nonnegative")
    if tolerance < 0 or not np.isfinite(tolerance):
        raise ValueError("Manifold tolerance must be finite and nonnegative")
    native_geometry = read(native_root / "geometry.json")
    if native_geometry.get("unit") != "m" or native_geometry.get("coordinate_system") != "RF_X_FORWARD_Z_UP":
        raise ValueError("Native geometry must use metres and RF coordinates")
    vertices = np.load(native_root / "arrays/vertices.npy", mmap_mode="r")
    triangles = np.load(native_root / "arrays/triangles.npy", mmap_mode="r")
    _validate_arrays(vertices, triangles)
    points = point_file(points_path)
    if point_indices is None:
        point_indices = list(range(len(points)))
    if not point_indices or any(i < 0 or i >= len(points) for i in point_indices):
        raise ValueError("Point indices are outside the Foundation witness file")
    points = points[np.asarray(point_indices, dtype=np.int64)]
    input_hashes = {
        "native_geometry.json": file_hash(native_root / "geometry.json"),
        "native_candidate.obj": file_hash(native_root / "candidate.obj"),
        "native_arrays/vertices.npy": file_hash(native_root / "arrays/vertices.npy"),
        "native_arrays/triangles.npy": file_hash(native_root / "arrays/triangles.npy"),
        "foundation_points.obj": file_hash(points_path),
        "repair_script": file_hash(Path(__file__)),
    }
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    method = METHOD if not tolerance else METHOD + "_tolerance"
    try:
        input_vertices = np.array(vertices, dtype=np.float64, order="C", copy=True)
        input_triangles = np.array(triangles, dtype=np.uint64, order="C", copy=True)
        print("MANIFOLD_LOCAL_COMPONENT_IMPORT_BEGIN", len(input_vertices), len(input_triangles), flush=True)
        manifold = manifold_backend(REPO)
        body = manifold.Manifold(manifold.Mesh64(input_vertices, input_triangles, tolerance=0.0))
        status = str(body.status())
        if body.status() != manifold.Error.NoError or body.num_tri() == 0:
            raise ValueError("Manifold did not accept native surface: " + status)
        components = list(body.decompose())
        print("MANIFOLD_LOCAL_COMPONENTS_DECOMPOSED", len(components), flush=True)
        records, selected_ids = select_components(components, points, float(padding))
        print("MANIFOLD_LOCAL_COMPONENT_SELECTION", json.dumps({
            "selected": selected_ids,
            "selected_triangles": sum(records[i]["triangles"] for i in selected_ids),
            "points": point_indices,
        }), flush=True)
        if not selected_ids:
            raise ValueError("No local components selected")
        selected = [components[i] for i in selected_ids]
        if tolerance:
            selected = [component.set_tolerance(float(tolerance)) for component in selected]
        if self_union:
            method += "_self_union"
            if len(selected) == 1:
                joined = selected[0] + selected[0]
                operation = "selected_component_plus_itself"
            else:
                selected_union = manifold.Manifold.batch_boolean(selected, manifold.OpType.Add)
                if selected_union.status() != manifold.Error.NoError:
                    raise ValueError("Selected component batch union failed before self-union: " + str(selected_union.status()))
                joined = selected_union + selected_union
                operation = "selected_components_batch_union_plus_itself"
        else:
            joined = manifold.Manifold.batch_boolean(selected, manifold.OpType.Add)
            operation = "selected_components_batch_union"
        union_status = str(joined.status())
        print("MANIFOLD_LOCAL_COMPONENT_UNION_RESULT", union_status, joined.num_tri(), flush=True)
        if joined.status() != manifold.Error.NoError or joined.num_tri() == 0:
            raise ValueError("Local component union failed: " + union_status)
        selected_vertices, selected_triangles = mesh_arrays(joined.to_mesh64())
        untouched_vertices = []
        untouched_triangles = []
        vertex_offset = len(selected_vertices)
        for index, component in enumerate(components):
            if index in selected_ids:
                continue
            component_vertices, component_triangles = mesh_arrays(component.to_mesh64())
            untouched_vertices.append(component_vertices)
            untouched_triangles.append(component_triangles + vertex_offset)
            vertex_offset += len(component_vertices)
        if untouched_vertices:
            out_vertices = np.concatenate([selected_vertices, *untouched_vertices], axis=0)
            out_triangles = np.concatenate([selected_triangles, *untouched_triangles], axis=0)
        else:
            out_vertices, out_triangles = selected_vertices, selected_triangles
        _validate_arrays(out_vertices, out_triangles)
        record = save_candidate(
            output, out_vertices, out_triangles, native_geometry, input_hashes,
            records, selected_ids, point_indices, padding, time.monotonic() - started,
            method, tolerance, float(joined.get_tolerance()),
            operation,
        )
        record["union_status"] = union_status
        record["selected_union_counts"] = {
            "vertices": int(len(selected_vertices)),
            "triangles": int(len(selected_triangles)),
        }
        record["joined_volume_m3"] = float(joined.volume())
        record["requested_tolerance_m"] = float(tolerance)
        record["joined_tolerance_m"] = float(joined.get_tolerance())
        write(output / "repair.json", record)
        print("MANIFOLD_LOCAL_COMPONENT_SAVED", json.dumps(record["output_counts"]), flush=True)
        return record
    except BaseException as exc:
        write(output / "repair-failure.json", dict(
            schema_version="phase1-cycle-local-component-union-1",
            status="FAIL", method=method, input_hashes=input_hashes,
            error=str(exc), requested_tolerance_m=float(tolerance),
            elapsed_s=time.monotonic() - started,
        ))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--padding", type=float, default=1e-6)
    parser.add_argument("--tolerance", type=float, default=0.0)
    parser.add_argument("--self-union", action="store_true")
    parser.add_argument("--point-index", type=int, action="append")
    args = parser.parse_args()
    repair(args.input, args.points, args.output, args.padding, args.point_index,
           args.tolerance, args.self_union)


if __name__ == "__main__":
    main()
