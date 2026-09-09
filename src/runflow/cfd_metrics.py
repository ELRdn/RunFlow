"""Strict OpenFOAM Foundation 14 force and residual parsing (Phase 1 smoke).

Baseline fixture note: private/baseline/run-003 is used only as format
evidence for the exact forces.dat and residuals.dat layout. It is not
human CFD validation and must never imply aerodynamic approval.

Supported forces header (OpenFOAM Foundation 14 forcesIncompressible):

    # Forces
    # CofR          : (0.00000000e+00 0.00000000e+00 0.00000000e+00)
    # Time          forces(pressure viscous)  moments(pressure viscous)

Data rows carry 13 numbers: time, pressure xyz, viscous xyz,
moment-pressure xyz, moment-viscous xyz. Forces are already Newtons
(rhoInf is applied inside the function object), so this module never
multiplies by density. Drag is minus Fx for inlet direction (-1, 0, 0).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

REQUIRED_RESIDUAL_FIELDS = ("p", "Ux", "Uy", "Uz", "k", "omega")
P_THRESHOLD = 1e-4
UKW_THRESHOLD = 1e-5
DRAG_SHIFT_TOL = 0.01
DRAG_RANGE_TOL = 0.02
FLUX_TOL = 0.001
MIN_LAST_ITERATION = 300
FORCES_WINDOW = 200
STATS_WINDOW = 100


def _key(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite iteration")
    if number.is_integer():
        return int(number)
    return number


def _clean_number(token, where):
    try:
        return float(token)
    except ValueError:
        raise ValueError("Invalid numeric token in " + where + ": " + repr(token))


def read_forces(path):
    present = Path(path).read_text(encoding="utf-8-sig")
    header_ok = False
    for line in present.splitlines():
        if line.lstrip().startswith("#") and "forces(pressure" in line.lower():
            header_ok = True
            break
    if not header_ok:
        raise ValueError("Unsupported forces.dat header")
    rows = []
    previous = None
    for raw in present.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cleaned = raw.replace("(", " ").replace(")", " ").replace(",", " ")
        tokens = cleaned.split()
        if len(tokens) != 13:
            raise ValueError("forces.dat row must carry 13 numbers")
        values = [_clean_number(token, "forces.dat") for token in tokens]
        for value in values:
            if not math.isfinite(value):
                raise ValueError("Non-finite value in forces.dat")
        iteration = float(values[0])
        if previous is not None and not iteration > previous:
            raise ValueError("forces.dat times must strictly increase")
        previous = iteration
        pressure = [float(values[1]), float(values[2]), float(values[3])]
        viscous = [float(values[4]), float(values[5]), float(values[6])]
        total = [p + v for p, v in zip(pressure, viscous)]
        rows.append(
            {
                "iteration": iteration,
                "pressure": pressure,
                "viscous": viscous,
                "total": total,
                "drag_N": float(-total[0]),
            }
        )
    if not rows:
        raise ValueError("forces.dat carries no data rows")
    return rows


def _parse_residuals_dat(present):
    fields = None
    results = {}
    for raw in present.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip().split()
            if body and body[0].lower() == "time" and len(body) >= 2 and fields is None:
                fields = body[1:]
            continue
        if fields is None:
            raise ValueError("residuals.dat header with Time and fields is required")
        parts = stripped.split()
        if len(parts) != len(fields) + 1:
            raise ValueError("residuals.dat column count mismatch")
        iteration = _key(_clean_number(parts[0], "residuals.dat"))
        entry = results.setdefault(iteration, {})
        for name, token in zip(fields, parts[1:]):
            if token.strip().lower() == "n/a":
                continue
            value = _clean_number(token, "residuals.dat")
            if not math.isfinite(value):
                raise ValueError("Non-finite residual in residuals.dat")
            if name in entry:
                entry[name] = max(entry[name], value)
            else:
                entry[name] = value
    if not results:
        raise ValueError("residuals.dat carries no data rows")
    return results


def _normalize_log_field(name):
    cleaned = name.strip()
    if len(cleaned) > 5 and cleaned.endswith("Final"):
        cleaned = cleaned[: -len("Final")]
    return cleaned


def _parse_solver_log(present):
    results = {}
    current = None
    saw_time = False
    for raw in present.splitlines():
        stripped = raw.strip()
        low = stripped.lower()
        if re.match(r'^Time\s*=', stripped):
            rhs = stripped.split("=", 1)[1].strip()
            if len(rhs) > 1 and rhs[-1:].lower() == "s":
                rhs = rhs[:-1].strip()
            head = rhs.split()
            if not head:
                continue
            current = _key(_clean_number(head[0], "solver log Time"))
            results.setdefault(current, {})
            saw_time = True
            continue
        if "solving for" in low and "initial residual" in low and "=" in stripped:
            if current is None:
                continue
            marker = "solving for"
            pos = low.find(marker)
            comma = stripped.find(",", pos)
            if comma < 0:
                continue
            field = _normalize_log_field(stripped[pos + len(marker):comma].strip())
            if not field:
                continue
            marker2 = "initial residual"
            pos2 = low.find(marker2)
            eq = stripped.find("=", pos2)
            if eq < 0:
                continue
            tail = stripped[eq + 1:].strip()
            if not tail:
                continue
            token = tail.split()[0].strip().strip(",;")
            value = _clean_number(token, "solver log residual")
            if not math.isfinite(value):
                raise ValueError("Non-finite residual in solver log")
            entry = results.setdefault(current, {})
            if field in entry:
                entry[field] = max(entry[field], value)
            else:
                entry[field] = value
    if not saw_time or not any(results.values()):
        raise ValueError("Solver log carries no Time and Solving-for entries")
    return results


def read_residuals(path):
    present = Path(path).read_text(encoding="utf-8-sig")
    if "solving for" in present.lower():
        return _parse_solver_log(present)
    return _parse_residuals_dat(present)


def _sorted_forces(forces):
    problems = []
    if not isinstance(forces, list) or not forces:
        return [], ["forces: empty trace"]
    normalized = []
    seen = set()
    for index, row in enumerate(forces):
        try:
            iteration = float(row["iteration"])
            drag = float(row["drag_N"])
        except (KeyError, TypeError, ValueError):
            problems.append("forces: missing iteration or drag_N at index " + str(index))
            continue
        if not math.isfinite(iteration) or not math.isfinite(drag):
            problems.append("forces: non-finite iteration or drag at index " + str(index))
            continue
        if iteration in seen:
            problems.append("forces: duplicate iteration " + repr(iteration))
            continue
        seen.add(iteration)
        normalized.append((iteration, drag))
    normalized.sort(key=lambda item: item[0])
    for earlier, later in zip(normalized, normalized[1:]):
        if not later[0] > earlier[0]:
            problems.append("forces: iterations must strictly increase")
            break
    return normalized, problems


def assess(forces, residuals, flux_balance, protocol=None):
    _ = protocol
    reasons = []
    metrics = {}
    ordered, force_problems = _sorted_forces(forces)
    reasons.extend(force_problems)
    by_iteration = {iteration: drag for iteration, drag in ordered}
    last_iteration = ordered[-1][0] if ordered else None
    metrics["n_force_rows"] = len(ordered)
    metrics["last_iteration"] = last_iteration
    window_mean = None
    if last_iteration is None:
        reasons.append("forces: missing trace, cannot establish window")
        return {"converged": False, "reasons": reasons, "window_mean_drag_N": None, "metrics": metrics}
    if not float(last_iteration).is_integer():
        reasons.append("forces: last iteration is not integral")
    last_int = int(round(float(last_iteration)))
    if last_int < MIN_LAST_ITERATION:
        reasons.append("forces: last iteration below minimum 300")
    window200 = list(range(last_int - FORCES_WINDOW + 1, last_int + 1))
    window100 = list(range(last_int - STATS_WINDOW + 1, last_int + 1))
    missing_forces = [step for step in window200 if step not in by_iteration]
    if missing_forces:
        reasons.append("forces: incomplete last200 consecutive iterations")
    last_drags = None
    prev_drags = None
    if not missing_forces and last_int >= MIN_LAST_ITERATION and not force_problems:
        last_drags = [float(by_iteration[step]) for step in window100]
        prev_drags = [float(by_iteration[step]) for step in window200[:STATS_WINDOW]]
    if last_drags is not None and prev_drags is not None:
        if any(not math.isfinite(value) for value in last_drags + prev_drags):
            reasons.append("forces: non-finite drag in convergence window")
        else:
            window_mean = sum(last_drags) / len(last_drags)
            prev_mean = sum(prev_drags) / len(prev_drags)
            metrics["window_mean_drag_N"] = window_mean
            metrics["prev100_mean_drag_N"] = prev_mean
            metrics["last100_min_drag_N"] = min(last_drags)
            metrics["last100_max_drag_N"] = max(last_drags)
            if not math.isfinite(window_mean) or window_mean <= 0:
                reasons.append("forces: window mean drag is zero, negative, or non-finite")
            else:
                shift = abs(window_mean - prev_mean) / abs(window_mean)
                spread = (max(last_drags) - min(last_drags)) / abs(window_mean)
                metrics["drag_mean_shift_rel"] = shift
                metrics["drag_range_rel"] = spread
                if shift > DRAG_SHIFT_TOL:
                    reasons.append("forces: drag mean shift exceeds 0.01")
                if spread > DRAG_RANGE_TOL:
                    reasons.append("forces: drag range exceeds 0.02")
    metrics.setdefault("window_mean_drag_N", window_mean)
    max_residuals = {}
    if not isinstance(residuals, dict) or not residuals:
        reasons.append("residuals: empty trace")
    elif last_int >= MIN_LAST_ITERATION and not missing_forces:
        for field in REQUIRED_RESIDUAL_FIELDS:
            values = []
            missed = False
            for step in window100:
                entry = residuals.get(step, residuals.get(float(step)))
                if not isinstance(entry, dict) or field not in entry:
                    reasons.append("residuals: missing field at iteration " + str(step) + ": " + field)
                    missed = True
                    break
                try:
                    number = float(entry[field])
                except (TypeError, ValueError):
                    reasons.append("residuals: invalid value at iteration " + str(step) + ": " + field)
                    missed = True
                    break
                if not math.isfinite(number):
                    reasons.append("residuals: non-finite value at iteration " + str(step) + ": " + field)
                    missed = True
                    break
                values.append(number)
            if not missed:
                peak = max(values)
                max_residuals[field] = peak
                limit = P_THRESHOLD if field == "p" else UKW_THRESHOLD
                if peak > limit:
                    reasons.append("residuals: max " + field + " exceeds limit over last100")
    metrics["max_residual_last100"] = max_residuals
    flux_by_iteration = {}
    if not isinstance(flux_balance, list) or not flux_balance:
        reasons.append("flux: empty trace")
    else:
        for index, row in enumerate(flux_balance):
            try:
                raw_step = row["iteration"]
                inflow = float(row["inflow"])
                outflow = float(row["outflow"])
                key = int(raw_step) if float(raw_step).is_integer() else float(raw_step)
            except (KeyError, TypeError, ValueError):
                reasons.append("flux: missing iteration, inflow, or outflow at index " + str(index))
                continue
            if not math.isfinite(inflow) or not math.isfinite(outflow):
                reasons.append("flux: non-finite flows at index " + str(index))
                continue
            if inflow <= 0 or outflow <= 0:
                reasons.append("flux: non-positive flow magnitude at index " + str(index))
                continue
            if key in flux_by_iteration:
                reasons.append("flux: duplicate iteration " + str(key))
                continue
            flux_by_iteration[key] = (inflow, outflow)
    max_flux_rel = None
    if last_int >= MIN_LAST_ITERATION and not missing_forces and flux_by_iteration:
        rels = []
        complete = True
        for step in window100:
            pair = flux_by_iteration.get(step, flux_by_iteration.get(float(step)))
            if pair is None:
                reasons.append("flux: missing iteration in last100: " + str(step))
                complete = False
                break
            inflow, outflow = pair
            rel = abs(inflow - outflow) / abs(inflow)
            if not math.isfinite(rel):
                reasons.append("flux: non-finite balance at iteration " + str(step))
                complete = False
                break
            rels.append(rel)
        if complete and rels:
            max_flux_rel = max(rels)
            metrics["max_flux_rel_last100"] = max_flux_rel
            if max_flux_rel > FLUX_TOL:
                reasons.append("flux: max net over inflow exceeds 0.001 over last100")
    metrics.setdefault("max_flux_rel_last100", max_flux_rel)
    metrics["thresholds"] = {
        "p": P_THRESHOLD,
        "U_k_omega": UKW_THRESHOLD,
        "drag_shift": DRAG_SHIFT_TOL,
        "drag_range": DRAG_RANGE_TOL,
        "flux": FLUX_TOL,
        "min_last_iteration": MIN_LAST_ITERATION,
    }
    converged = not reasons
    return {
        "converged": converged,
        "reasons": reasons,
        "window_mean_drag_N": window_mean,
        "metrics": metrics,
    }


def coefficients(drag, rho, speed, area):
    try:
        drag_value = float(drag)
        rho_value = float(rho)
        speed_value = float(speed)
        area_value = float(area)
    except (TypeError, ValueError):
        raise ValueError("coefficients require numeric drag, rho, speed, and area")
    if not math.isfinite(drag_value):
        raise ValueError("drag must be finite")
    if not math.isfinite(rho_value) or rho_value <= 0:
        raise ValueError("density must be positive and finite")
    if not math.isfinite(speed_value) or speed_value <= 0:
        raise ValueError("speed must be positive and finite")
    if not math.isfinite(area_value) or area_value <= 0:
        raise ValueError("area must be positive and finite")
    dynamic_pressure = 0.5 * rho_value * speed_value * speed_value
    cda = drag_value / dynamic_pressure
    return {"drag_N": drag_value, "Cd": cda / area_value, "CdA_m2": cda}
