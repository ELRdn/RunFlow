"""Execution-resource profiles, kept separate from scientific protocol identity.

A profile describes how many isolated workers and MPI ranks the host may run.
It is execution provenance only: it is recorded with a run and never folded
into the numerical family that decides which results may be aggregated.
"""
from __future__ import annotations

SCHEMA_VERSION = "phase1-execution-profile-1"
LOGICAL_CPU_DEFAULT = 24

# Measured host: Ryzen 9 7900X, 12 cores / 24 logical processors.
PROFILES = {
    "interactive": dict(workers=1, ranks=4),
    "batch": dict(workers=2, ranks=8),
    "throughput": dict(workers=4, ranks=4),
    "maximum": dict(workers=6, ranks=4),
}

# Throughput benchmark grid required by the Phase A plan.
BENCHMARK_COMBINATIONS = ((1, 8), (2, 8), (4, 4), (6, 4))


def resolve(name, host_logical=None, reserve_cpu=2):
    """Return a concrete, validated execution profile.

    Raises ValueError when the profile would oversubscribe the host, so a
    caller can never silently ask for more ranks than the machine has.
    """
    if name not in PROFILES:
        raise ValueError("Unknown execution profile: " + str(name))
    base = PROFILES[name]
    logical = int(LOGICAL_CPU_DEFAULT if host_logical is None else host_logical)
    if logical <= 0:
        raise ValueError("Logical CPU count must be positive")
    reserve = int(reserve_cpu)
    if reserve < 0 or reserve >= logical:
        raise ValueError("CPU reserve must be smaller than the logical CPU count")
    workers = int(base["workers"])
    ranks = int(base["ranks"])
    if workers < 1 or ranks < 1:
        raise ValueError("Profile workers and ranks must be positive")
    usable = logical - reserve
    if workers * ranks > usable:
        raise ValueError(
            "Profile oversubscribes the host: %d workers x %d ranks > %d usable CPUs"
            % (workers, ranks, usable)
        )
    threads = max(1, usable // workers)
    return dict(
        schema_version=SCHEMA_VERSION,
        name=str(name),
        logical_cpu=logical,
        reserve_cpu=reserve,
        workers=workers,
        ranks=ranks,
        processes=ranks,
        threads_per_worker=threads,
        omp_threads=threads,
        blender_threads=threads,
    )


def resolve_pair(workers, ranks, host_logical=None, reserve_cpu=2):
    """Validate an ad-hoc worker/rank pair for the throughput benchmark."""
    logical = int(LOGICAL_CPU_DEFAULT if host_logical is None else host_logical)
    reserve = int(reserve_cpu)
    usable = logical - reserve
    workers = int(workers)
    ranks = int(ranks)
    if workers < 1 or ranks < 1:
        raise ValueError("Worker and rank counts must be positive")
    if workers * ranks > usable:
        raise ValueError(
            "Combination oversubscribes the host: %d workers x %d ranks > %d usable CPUs"
            % (workers, ranks, usable)
        )
    threads = max(1, usable // workers)
    return dict(
        schema_version=SCHEMA_VERSION,
        name="custom-%dx%d" % (workers, ranks),
        logical_cpu=logical,
        reserve_cpu=reserve,
        workers=workers,
        ranks=ranks,
        processes=ranks,
        threads_per_worker=threads,
        omp_threads=threads,
        blender_threads=threads,
    )
