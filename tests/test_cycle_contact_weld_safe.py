import numpy as np
import pytest
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "repair_cycle_contact_weld_safe", Path(__file__).resolve().parents[1] / "scripts/repair_cycle_contact_weld_safe.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
apply_pair = _module.apply_pair
nearest_pair = _module.nearest_pair
topology = _module.topology


def test_contact_weld_removes_only_collapsed_tetrahedron_faces_and_stays_closed():
    vertices = np.asarray([
        [0.0, 0.0, 0.0],
        [0.0001, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    triangles = np.asarray([
        [0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2],
    ], dtype=np.int64)
    result, error = apply_pair(vertices, triangles, 0, 1)
    assert error is None
    output_vertices, output_triangles, removed, loose, result_topology = result
    assert removed == 2
    assert loose == 1
    assert len(output_vertices) == 3
    assert len(output_triangles) == 2
    assert result_topology["boundary_edges"] == 0
    assert result_topology["nonmanifold_edges"] == 0
    assert topology(output_triangles)["max_edge_incidence"] == 2


def test_nearest_pair_enforces_the_two_millimetre_diagnostic_limit():
    vertices = np.asarray([[0.0, 0.0, 0.0], [0.0005, 0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float64)
    first, second, distance, first_distance, second_distance = nearest_pair(
        vertices, [0.0002, 0.0, 0.0], 0.002, 0.002
    )
    assert (first, second) == (0, 1)
    assert distance == pytest.approx(0.0005)
    assert first_distance == pytest.approx(0.0002)
    assert second_distance == pytest.approx(0.0003)
