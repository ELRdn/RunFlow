# Phase A7 - frame-parallel campaign runner (measured)

2026-09-14.

## Problem

The 32 phase samples are numerically independent, but the campaign ledger
(campaign.json and active.json) is single-writer by design. Two processes
writing it would corrupt the record, so the campaign ran strictly serially.

## Design

scripts/run_phase1_parallel_cycle.py adds isolated worker roots under a parent
campaign root:

    parent
      parallel-request.json
      parallel-campaign.json
      worker-00/  (own campaign.json and active.json)
      worker-01/
      ...

- Assignment is deterministic: frame index modulo worker count.
- The parent never writes campaign.json or active.json, so there is no shared
  mutable ledger.
- Worker count and MPI ranks come from an execution profile, never hard-coded.
  Profiles are interactive (1 x 4), batch (2 x 8), throughput (4 x 4) and
  maximum (6 x 4); resolve() refuses any profile that would oversubscribe the
  logical CPU count and gives each worker its own OMP and Blender thread budget.
- Resume: a worker root whose active.json holds a dead PID gets
  --recover-interrupted. A live PID raises instead, so a running campaign can
  never be duplicated.
- Aggregation reads every worker ledger, rejects a mix of numerical families,
  and writes a deterministic parallel-campaign.json.

## Measured gate

Two frames, two workers, four ranks each, on the audited frame-0 and frame-1
candidates. Output root E:/RunFlowPrivate/phase-a/parallel-gate-002.

| Observation | Value |
|---|---|
| Workers | 2 x 4 ranks (8 of 22 usable CPUs) |
| Frames | 0 and 1, both PASS |
| Wall time | 844.3 s for two frames |
| Serial equivalent (measured np=4) | 634.5 s per frame, about 1,235 s for two |
| Throughput gain | 1.46x |
| Numerical families | exactly one: 367d53e2d1585c5b... |
| frame 0 drag | 88.7838701710444 N |
| frame 1 drag | 91.0269342809181 N |

frame 0's drag in the parallel campaign is identical to the same frame's drag in
the standalone rank benchmark at the same rank count (88.7838701710444 N), which
is an independent confirmation that a worker produces the same physics as a
serial run.

## Interruption and resume

The same two-frame campaign was killed mid-flight (the runner, both worker
campaigns, and their children). Before the resume the worker roots held:

- worker-00/frame-00-001 partial
- worker-00/active.json pointing at the now-dead PID

Re-running the identical command archived both the partial frame and the dead
marker, then retried:

- frame-00-001.interrupted-20260913T162745Z
- active.interrupted-20260913T162745Z.json

Nothing was deleted, and the retry completed both frames. A second immediate
re-run skipped every completed frame: wall time fell from 844.3 s to 30.7 s
with no new attempts in the worker ledger and the same aggregate result.

## Aggregation refusal, observed in practice

The first attempt at the two-frame gate was refused with

    Parallel campaign mixes numerical families: {b3282b13...: [0], 64b3d71b...: [1]}

That was the correct behaviour and it exposed a real defect in the family
definition rather than in the runner: frame 0 and frame 1 had been repaired by
different local routes, so their per-frame repair_method and repair_max_weld_m
differed. Those fields are logged provenance, not comparison conditions
(EXPERIMENT_PROTOCOL section 3), and every frame's surface had already passed
the identical Foundation check and the identical 2 mm / 1% audit. The family now
excludes them while still separating on voxel size, weld tolerance, remesh pass
count, normal policy, mode, and fidelity gate. After the correction the two
frames share family 367d53e2d1585c5b.

## Tests

tests/test_phase_a.py covers deterministic assignment, isolated-ledger
aggregation, rejection of mixed families, and that per-frame repair provenance
no longer separates families while geometry-pipeline fields still do.
