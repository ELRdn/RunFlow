# Phase A1/A2/A3 - projection audit benchmark

2026-09-14. Measured on the frame-02 audit pair (source 14,035,756 triangles,
candidate 5,305,812 triangles). Machine-readable companion:
phase-a/projection-grid-ab.json in the private E: evidence root. Test inputs
were copied into D: scratch so no archived audit root was touched.

## A1 - precision grid A/B: rejected, no benefit

Full three-view runs cost about 40 minutes each, so the grid question was
answered on the front view, which exercises the same union code as the others.
The reference values come from the archived 1e-9 audit, which the refactored
CLI reproduced bit-for-bit.

| Grid | Front wall time | Source area m2 | IoU |
|---|---:|---:|---:|
| 1e-9 (baseline) | 873.25 s | 0.4782594611200226 | 0.9999999902994822 |
| 1e-7 | 908.81 s | 0.4782594567067515 | 0.9999999512301038 |

- Elapsed ratio coarse / legacy: 1.041 - the coarser grid is 4% slower.
- Numerical equivalence: source area differs by 9.2e-9 relative, candidate area
  by 1.5e-8, IoU by 3.9e-8. All far inside the 1e-3 and 0.999 acceptance floors.

The coarser grid is numerically indistinguishable but buys nothing. The
conclusion is that the projection cost is not resolution-driven: it is the GEOS
overlay over roughly 19 million triangles, which is resolution-independent. The
grid change is therefore rejected, 1e-9 stays the default, and no audit schema
v2 is introduced.

This is a useful negative result: the profiling hypothesis that the 1e-9 grid
was the dominant cost did not survive measurement.

## A2 - source projection cache: accepted, 3.85x on a re-run

Measured on the top view of the same audit root.

| Pass | Wall time | Source projection |
|---|---:|---|
| Cold (cache miss, entry written) | 1,046 s | 772 s computed |
| Warm (cache hit) | 271.8 s | skipped |

- Cache key: 72c2af83a950f2ae702101d86d4d63cf2cc1a5be36b2888dc54e0788fafe8488
- Recorded status on the warm pass: hit, version runflow-projection-cache-1.
- Source area identical across passes (0.44877570756655333).
- Speedup 1,046 / 271.8 = 3.85x for that view.

The saving applies whenever a frame is re-audited, and the same cache is reused
across the three views of one audit because the source does not change between
them. Candidates are never cached: each repair attempt has different geometry.

## A3 - three-view parallelism: accepted, 1.99x, numerically exact

All three views launched concurrently into one audit root, each writing only its
own per-view file, merged in the fixed front, side, top order after every view
reported success.

| Mode | Wall time | Failures |
|---|---:|---:|
| Serial (archived baseline, frame-02) | 2,500.6 s | 0 |
| Three views in parallel | 1,258.99 s | 0 |

Speedup 1.99x. Every view returned returncode 0 and its own log. Against the
archived canonical document the deltas are exactly zero: relative source area
delta 0.0, candidate delta 0.0, relative-change delta 0.0, and identical IoU for
all three views. The parallel result is numerically indistinguishable from the
serial one.

The speedup is bounded by the slowest view rather than by view count, so three
views yield about 2x, not 3x.

## Combined effect

| Configuration | Projection stage wall time |
|---|---:|
| Baseline serial, cold, 1e-9 | 2,500.6 s |
| Three views in parallel, cold | 1,259.0 s |
| One view warm (cache hit) | 271.8 s |

For a frame that is re-audited - the common case when a new repair candidate is
produced, or when one view timed out as in frame-03 - parallel views plus a warm
source cache put the stage near the slowest single candidate projection, roughly
600 s, against 2,500 s today. That is the real lever the profiling was looking
for, and it is not the precision grid.

## Tests

tests/test_phase_a.py covers: the production grid guard still rejecting a coarse
grid without --benchmark; the benchmark path marking its output; cache identity
changing with geometry, view, grid, axes, chunk size, and algorithm version;
corruption and empty-geometry entries reported as misses; cache-hit and
uncached runs agreeing on source area, candidate area, and IoU; parallel views
matching serial within each view's metrics; and a parallel merge passing the
authoritative-artifact validation.
