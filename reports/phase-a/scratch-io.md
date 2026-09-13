# Phase A4 - scratch architecture

2026-09-13.

## Problem

All high-churn work ran under E: - an I-O DATA USB HDD - reached from WSL as
/mnt/e through the 9p bridge. The existing notes already recorded the symptom:
ASCII VTK writes timed out with each rank waiting in p9_client_rpc. Every
projection audit also wrote a 285 MB object and a 410 MB diagnostics archive
per attempt onto the same disk.

## Design

Two non-authoritative scratch slots, both on the NVMe D: drive:

| Slot | Path | Used by |
|---|---|---|
| Windows scratch | D:/RunFlowScratch | Python and Blender stages, geometry, repair, audit I/O, reports |
| Linux scratch | /scratch (ext4 on D:) | the high-churn OpenFOAM case tree |

E: stays the authoritative archive. cfd_paths now exposes archive_roots(),
scratch_roots(), scratch_win(), scratch_wsl() and phase_a_root(); is_private()
accepts the scratch slots and the Phase A evidence root so the existing
private-output guards keep working, and reserve_reason() now applies a D:
reserve check to scratch paths instead of silently returning None.

The worker accepts --case-root, so the case tree can live on the Linux-native
filesystem while the frame root - which Blender must also reach - stays on the
Windows-visible scratch. The worker's disk accounting includes the case root so
the output-size gate still covers it. UNC paths such as wsl.localhost are not
used.

## Copy-back

src/runflow/scratch.py copies canonical artifacts back with a checksum
manifest. Reproducible or scratch-only trees (case, tool-sources,
projection-cache, prior-projection-output) stay in scratch; everything else is
copied atomically and recorded. verify_manifest() re-checks the archive bytes.
Nothing archived is ever deleted.

preflight() refuses to start when the D: reserve or the free-space floor is not
met, and warns when the Linux scratch is not mounted.

## Host configuration

.wslconfig and the disk layout are not modified automatically. The
recommendation is written to reports/phase-a/wslconfig-recommendation.md.

## Measured comparison

Pending. The three-way comparison (/mnt/e versus Windows scratch versus Linux
case scratch) for the mesh and solver stage will run after the projection grid
benchmark releases the host, and the numbers land in this file. The section is
intentionally left unclaimed rather than estimated.
