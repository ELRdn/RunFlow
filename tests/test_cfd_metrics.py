"""Targeted Phase 1 smoke tests for OpenFOAM Foundation 14 parsing.

Baseline files under private/baseline are format evidence only. These
tests embed the exact header plus synthetic rows, so they pass without
private assets and never claim human CFD validation.
"""
import math
from pathlib import Path

import pytest

from runflow.cfd_metrics import assess, coefficients, read_forces, read_residuals

FORCES_SAMPLE = """# Forces
# CofR          : (0.00000000e+00 0.00000000e+00 0.00000000e+00)
# Time          forces(pressure viscous)  moments(pressure viscous)
0               ((0.00000000e+00 0.00000000e+00 0.00000000e+00) (0.00000000e+00 0.00000000e+00 0.00000000e+00)) ((0.00000000e+00 0.00000000e+00 0.00000000e+00) (0.00000000e+00 0.00000000e+00 0.00000000e+00))
1               ((1.00000000e+00 2.00000000e+00 3.00000000e+00) (4.00000000e+00 5.00000000e+00 6.00000000e+00)) ((0.00000000e+00 0.00000000e+00 0.00000000e+00) (0.00000000e+00 0.00000000e+00 0.00000000e+00))
2               ((-2.50000000e+00 0.00000000e+00 0.00000000e+00) (5.00000000e-01 0.00000000e+00 0.00000000e+00)) ((0.00000000e+00 0.00000000e+00 0.00000000e+00) (0.00000000e+00 0.00000000e+00 0.00000000e+00))
"""

RESIDUALS_SAMPLE = """# Residuals
# Time             p               Ux              Uy              Uz              k               omega
0                N/A             N/A             N/A             N/A             N/A             N/A
1                1.00000000e+00  5.00000000e-01  4.00000000e-01  3.00000000e-01  2.00000000e-01  1.00000000e-01
2                8.00000000e-02  1.00000000e-03  1.00000000e-03  1.00000000e-03  1.00000000e-03  1.00000000e-03
"""

SOLVER_LOG_SAMPLE = """Starting time loop
Time = 4s
DICPCG:  Solving for p, Initial residual = 0.02, Final residual = 0.002, No Iterations 20
Time = 5s
DICPCG:  Solving for p, Initial residual = 0.02, Final residual = 0.002, No Iterations 20
DICPCG:  Solving for p, Initial residual = 0.09, Final residual = 0.008, No Iterations 22
smoothSolver:  Solving for Ux, Initial residual = 0.001, Final residual = 0.0001, No Iterations 5
smoothSolver:  Solving for Uy, Initial residual = 0.002, Final residual = 0.0002, No Iterations 5
smoothSolver:  Solving for Uz, Initial residual = 0.003, Final residual = 0.0003, No Iterations 5
smoothSolver:  Solving for k, Initial residual = 0.004, Final residual = 0.0004, No Iterations 5
smoothSolver:  Solving for omega, Initial residual = 0.005, Final residual = 0.0005, No Iterations 5
"""


def test_continuity_log_line_is_not_an_iteration_marker(tmp_path):
    p=tmp_path/'solver.log'
    p.write_text(SOLVER_LOG_SAMPLE+'\ntime step continuity errors : sum local = 2e-8, global = 1e-9, cumulative = 0\n')
    assert read_residuals(p)[5]['p']==.09


def write_tmp(tmp_path, name, content):
    target = tmp_path / name
    target.write_text(content, encoding="utf-8")
    return target


def make_triple():
    forces = []
    for step in range(1, 401):
        drag = 2.0 + 0.001 * math.sin(step)
        forces.append({"iteration": float(step), "pressure": [-drag, 0.0, 0.0], "viscous": [0.0, 0.0, 0.0], "total": [-drag, 0.0, 0.0], "drag_N": drag})
    residuals = {}
    for step in range(1, 401):
        residuals[step] = {"p": 5.0e-05, "Ux": 5.0e-06, "Uy": 5.0e-06, "Uz": 5.0e-06, "k": 5.0e-06, "omega": 5.0e-06}
    flux = []
    for step in range(1, 401):
        flux.append({"iteration": step, "inflow": 1.0, "outflow": 1.0 + 1.0e-05 * math.cos(step)})
    return forces, residuals, flux


def test_forces_exact_header_total_once_and_sign(tmp_path):
    rows = read_forces(write_tmp(tmp_path, "forces.dat", FORCES_SAMPLE))
    assert len(rows) == 3
    summed = rows[1]
    assert summed["pressure"] == pytest.approx([1.0, 2.0, 3.0])
    assert summed["viscous"] == pytest.approx([4.0, 5.0, 6.0])
    assert summed["total"] == pytest.approx([5.0, 7.0, 9.0])
    assert summed["drag_N"] == pytest.approx(-5.0)
    drag_row = rows[2]
    assert drag_row["total"] == pytest.approx([-2.0, 0.0, 0.0])
    assert drag_row["drag_N"] == pytest.approx(2.0)


def test_forces_no_density_scaling(tmp_path):
    content = FORCES_SAMPLE.replace(
        "((1.00000000e+00 2.00000000e+00 3.00000000e+00) (4.00000000e+00 5.00000000e+00 6.00000000e+00))",
        "((1.00000000e+00 0.00000000e+00 0.00000000e+00) (5.00000000e-01 0.00000000e+00 0.00000000e+00))",
    )
    rows = read_forces(write_tmp(tmp_path, "forces.dat", content))
    assert rows[1]["total"][0] == pytest.approx(1.5)
    assert rows[1]["drag_N"] == pytest.approx(-1.5)


def test_forces_rejects_duplicate_decreasing_and_nonfinite(tmp_path):
    dup_row = "2               ((-2.50000000e+00 0.00000000e+00 0.00000000e+00) (5.00000000e-01 0.00000000e+00 0.00000000e+00)) ((0.00000000e+00 0.00000000e+00 0.00000000e+00) (0.00000000e+00 0.00000000e+00 0.00000000e+00))"
    with pytest.raises(ValueError):
        read_forces(write_tmp(tmp_path, "a.dat", FORCES_SAMPLE + dup_row + chr(10)))
    with pytest.raises(ValueError):
        read_forces(write_tmp(tmp_path, "b.dat", "Time 1.0 2.0" + chr(10)))
    nonfinite = FORCES_SAMPLE.replace("(1.00000000e+00", "(inf", 1)
    with pytest.raises(ValueError):
        read_forces(write_tmp(tmp_path, "c.dat", nonfinite))


def test_residuals_dat_values_and_na(tmp_path):
    parsed = read_residuals(write_tmp(tmp_path, "residuals.dat", RESIDUALS_SAMPLE))
    assert parsed[1]["p"] == pytest.approx(1.0)
    assert parsed[2]["Ux"] == pytest.approx(1.0e-03)
    assert 0 not in parsed or parsed.get(0, {}) == {}


def test_residuals_log_keeps_max_repeated_pressure(tmp_path):
    parsed = read_residuals(write_tmp(tmp_path, "foamRun.log", SOLVER_LOG_SAMPLE))
    assert parsed[5]["p"] == pytest.approx(0.09)
    assert parsed[5]["Ux"] == pytest.approx(0.001)
    assert parsed[5]["omega"] == pytest.approx(0.005)


def test_assess_passes_converged_window():
    forces, residuals, flux = make_triple()
    out = assess(forces, residuals, flux)
    assert out["converged"] is True
    assert out["reasons"] == []
    assert out["window_mean_drag_N"] == pytest.approx(2.0, rel=0.01)
    assert out["metrics"]["max_residual_last100"]["p"] == pytest.approx(5.0e-05)


def test_assess_rejects_drifting_and_wide_range():
    forces, residuals, flux = make_triple()
    for row in forces:
        if row["iteration"] >= 301:
            row["total"] = [-2.06, 0.0, 0.0]
            row["pressure"] = [-2.06, 0.0, 0.0]
            row["drag_N"] = 2.06
    assert assess(forces, residuals, flux)["converged"] is False
    forces2, residuals2, flux2 = make_triple()
    forces2[-1]["drag_N"] = 2.2
    forces2[-1]["total"] = [-2.2, 0.0, 0.0]
    forces2[-1]["pressure"] = [-2.2, 0.0, 0.0]
    assert assess(forces2, residuals2, flux2)["converged"] is False


def test_assess_rejects_missing_velocity_residual_and_flux():
    forces, residuals, flux = make_triple()
    missing_ux = {step: {key: value for key, value in entry.items() if key != "Ux"} for step, entry in residuals.items()}
    assert assess(forces, missing_ux, flux)["converged"] is False
    thin_residuals = {step: entry for step, entry in residuals.items() if step < 350}
    assert assess(forces, thin_residuals, flux)["converged"] is False
    thin_flux = [row for row in flux if row["iteration"] < 350]
    assert assess(forces, residuals, thin_flux)["converged"] is False


def test_assess_rejects_residual_threshold_and_flux_imbalance():
    forces, residuals, flux = make_triple()
    residuals[400]["p"] = 2.0e-04
    assert assess(forces, residuals, flux)["converged"] is False
    forces_ok, residuals_ok, flux_ok = make_triple()
    flux_ok[-1]["outflow"] = 1.02
    assert assess(forces_ok, residuals_ok, flux_ok)["converged"] is False


def test_assess_rejects_nonfinite_zero_negative_duplicate_and_short():
    forces, residuals, flux = make_triple()
    forces[399]["drag_N"] = float("inf")
    assert assess(forces, residuals, flux)["converged"] is False
    forces, residuals, flux = make_triple()
    for row in forces:
        row["drag_N"] = -1.0
        row["total"] = [1.0, 0.0, 0.0]
        row["pressure"] = [1.0, 0.0, 0.0]
    assert assess(forces, residuals, flux)["converged"] is False
    forces, residuals, flux = make_triple()
    forces.append(dict(forces[-1]))
    assert assess(forces, residuals, flux)["converged"] is False
    assert assess(forces[:150], residuals, flux)["converged"] is False
    gapped_forces, gapped_residuals, gapped_flux = make_triple()
    gapped = [row for row in gapped_forces if row["iteration"] != 250]
    assert assess(gapped, gapped_residuals, gapped_flux)["converged"] is False


def test_coefficients_dynamic_pressure():
    out = coefficients(1.5, 1.2, 2.0, 0.5)
    assert out["drag_N"] == pytest.approx(1.5)
    assert out["CdA_m2"] == pytest.approx(0.625)
    assert out["Cd"] == pytest.approx(1.25)
    with pytest.raises(ValueError):
        coefficients(1.0, 0.0, 2.0, 0.5)


def test_baseline_header_format_evidence_only():
    candidate = Path("private/baseline/run-003/case/postProcessing/forcesIncompressible/0/forces.dat")
    if not candidate.is_file():
        pytest.skip("baseline fixture absent; embedded header covers the format")
    head = candidate.read_text(encoding="utf-8-sig").splitlines()[:3]
    assert head[0].strip() == "# Forces"
    assert "forces(pressure viscous)" in head[2]
    rows = read_forces(candidate)
    assert len(rows) > 10
    sample = rows[1]
    summed = [p + v for p, v in zip(sample["pressure"], sample["viscous"])]
    assert sample["total"] == pytest.approx(summed)
    assert sample["drag_N"] == pytest.approx(-summed[0])
