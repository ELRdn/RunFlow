# Phase A6 - execution resources and numerical family (measured)

2026-09-14.

## Problem

cycle_family() hashed the whole protocol object, which included limits:
processes, memory_bytes, output_bytes, and every stage and total time budget.
Two runs of identical physics at a different rank count therefore landed in
different numerical families, and gait_cycle.aggregate() refuses to aggregate
across families. That made every execution-tuning experiment a family fork.

## Change

cycle_family() now hashes only values that can change the scientific result:

- excluded: limits (process count, memory/output budget, stage and total time)
- excluded: the frame index, the per-frame cycle block, and the diagnostic
  refinement's source snapshot
- excluded after the A7 finding: per-frame repair provenance (repair_method and
  repair_max_weld_m), because EXPERIMENT_PROTOCOL section 3 logs per-frame
  topology repairs without making them a comparison condition
- still included: physics, domain, mesh policy, voxel size, weld tolerance,
  degenerate-face threshold, remesh pass count, normal policy, mode, fidelity
  gate, and every convergence threshold

CYCLE_FAMILY_VERSION moved from phase1-cycle-family-1 to phase1-cycle-family-2.
Execution identity is recorded separately in execution-profile.json inside each
frame root: the effective limits, the requested override, its source, the
explicit note that limits are excluded from the scientific identity, and the
family hash. apply_execution() rejects any override key outside the
execution-only set, so a resource experiment cannot alter the numerical
contract.

## Step 1 - numerical independence of the rank count

frame-00 prepared and executed twice in fresh Phase A roots from the same
audited candidate, differing only in the execution override.

| Quantity | np = 4 | np = 8 | Relative delta |
|---|---:|---:|---:|
| Drag | 88.7838701710444 N | 88.73899919663211 N | 5.05e-4 |
| Cd | 0.7787811708851297 | 0.7783875783336421 | 5.05e-4 |
| CdA | 0.36993279237935167 | 0.3697458299859671 | 5.05e-4 |
| Cells | 512,670 | 512,729 | 1.15e-4 |
| Solver iterations | 543 | 538 | - |
| Mesh stage | 230.6 s | 237.4 s | - |
| Solver stage | 297.5 s | 219.5 s | 1.36x faster |
| Frame wall time | 634.5 s | 559.3 s | 1.13x faster |

- Both runs PASS every convergence and mesh gate.
- Physics delta 5.05e-4 is well inside the existing protocol tolerance
  (mean_drag_relative 1e-2). No threshold was changed to reach this.
- Cell count differs by 59 cells (1.15e-4). Parallel snappyHexMesh legitimately
  produces a slightly different count at partition boundaries; the protocol
  constrains the mesh through the checkMesh, refinement-level and cell-limit
  gates, all of which pass, and does not require an identical cell count across
  rank counts. This is reported as an observation with an engineering sanity
  bound of 1%, not as a relaxed scientific tolerance.
- Both runs carry the same comparison family, which is the point of the family
  redesign: 367d53e2d1585c5b... at both rank counts.
- np = 8 helps the solver (1.36x) but not the mesh, which does not scale at this
  cell count. The frame-level gain is 1.13x.

## Step 2 - throughput

The bounded two-frame gate in Phase A7 measured the actual campaign behaviour:
2 workers x 4 ranks finished two frames in 844.3 s against roughly 1,235 s
serially, a 1.46x throughput gain while leaving 14 of 22 usable CPUs idle for
the desktop. Frame-level rank scaling and worker-level parallelism are therefore
two separate levers, and the worker level is at least as valuable because it
also keeps any single rank count small enough to stay responsive.

The 1x8 / 2x8 / 4x4 / 6x4 sweep is not claimed: only 2x4 has been measured, and
reporting the others without measurement would be estimation. The profiles for
all four exist and are validated for oversubscription, so the sweep remains a
bounded follow-up.

## Step 3 - family semantics

Verified directly against the executed protocols:

- Same frame at 4 and 8 ranks: one family.
- frame 0 and frame 1 (different repair routes): one family after the fix.
- Changing voxel size: different family.
- Changing fidelity gate: different family.
- Changing weld radius alone: same family.
- Same frame across the A6 and A7 roots: same family.
- A non-execution override key is rejected.

## Tests

tests/test_phase_a.py covers the version constant, execution-only overrides,
rejection of non-execution keys, family equality across rank counts, family
separation on scientific inputs, and the repair-provenance exclusion.
