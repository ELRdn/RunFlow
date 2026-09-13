# Phase A0 - Baseline and safety snapshot

2026-09-13. Recorded before any performance change. Machine-readable companion
in the private E: evidence root (phase-a/phase-a-baseline.json).

## Repository state

- HEAD 2150939 on main, equal to origin/main.
- Untracked: scripts/__patch_probe2.tmp and scripts/__probe_empty.tmp (probe
  residue from 2026-09-07; deliberately left in place, no tracked change).
- Existing test suite before Phase A: 369 passed in 36.8 s.

## Target code paths confirmed in the current repository

| Purpose | Location |
|---|---|
| Projection audit CLI and precision guard | scripts/audit_shape_projection.py |
| Two-dimensional union and comparison | src/runflow/shape_projection.py |
| Surface cache and distance sampling | src/runflow/shape_audit.py |
| Cycle orchestration and numerical family | src/runflow/cfd_cycle.py |
| Nested sampling contract | src/runflow/gait_cycle.py |
| Resource guard and OS commit cap | src/runflow/shape_resources.py, scripts/repair_trial_support.py |
| Loop campaign and single-writer ledger | scripts/run_phase1_full_cycle.py |
| Private-root restriction | src/runflow/cfd_paths.py |
| WSL worker and MPI ranks | scripts/cfd_worker.py, src/runflow/cfd.py |

## Differences from the profiling report

The profiling report matches the code on every material point. Three additions:

1. cfd.private() hard-codes the allowed output roots to the repository private
   directory or the E: archive, so any scratch relocation must extend that
   check first.
2. The cycle lane does not schema-validate its protocol, so an execution-only
   limit override is possible without touching the scientific schema.
3. reserve_reason() returned None for any non-archive path, so scratch roots had
   no preflight before this change.

## Baseline configuration and paths

- Projection precision grid 1e-9 m; the CLI rejects anything coarser than 1e-8 m.
- limits.processes = 4; memory 12 GiB; output 10 GiB; total 3600 s.
- Archive roots: repository private/ and E:/RunFlowPrivate/phase1.
- E: is an I-O DATA HDCX-UT on USB; C: and D: are NVMe.

## Baseline stage timings (frame-00, measured)

| Stage | Seconds |
|---|---:|
| surface (surfaceCheck) | 78.6 |
| mesh total | 276.7 |
| - blockMesh | 3.3 |
| - surfaceFeatures | 29.8 |
| - decomposePar | 6.8 |
| - snappyHexMesh | 227.3 |
| - checkMesh | 6.2 |
| solver total | 357.3 |
| - potentialFoam | 6.5 |
| - foamRun (545 iterations) | 348.1 |
| fields (foamToVTK) | 7.9 |
| report | 5.8 |
| frame total | 745.4 |

Frame-01 616.1 s, frame-02 about 600 s. Mesh 512,670 cells, maximum aspect
ratio 19.9.

## Baseline projection audit (frame-02, measured)

- Wall time 2,500.6 s at a 1e-9 m precision grid; frame-03 timed out at 3,660.6 s.
- Source 14,035,756 triangles / 7,023,770 vertices.
- Candidate 5,305,812 triangles / 2,658,796 vertices.

## Baseline ledger

- cycle-phase1-full-001: consumed 18,743.6 s of an 86,400 s budget, cycle
  6,880.5 s, repair and audit 4,918.2 s.
- Composite execution records under the campaign root: 19, total 1,912.0 s.

## Archive volume

| Tree | Files | GiB |
|---|---:|---:|
| cycle-repair-campaign-001 | 1,507 | 104.54 |
| cycle-native-discovery-001 | 696 | 49.66 |
| cycle-phase1-full-001 | 807 | 4.47 |
| phase1 total | - | 253.62 |

## A0 gate

Baseline reproducible; every target code path identified. No performance
optimization had been applied at this point.
