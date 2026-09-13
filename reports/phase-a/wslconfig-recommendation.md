# WSL host configuration recommendation

2026-09-13. Recommendation only. Nothing here was applied automatically.

## Current state

%UserProfile%/.wslconfig sets networkingMode, firewall and dnsTunneling only.
There is no processor or memory limit, so WSL2 may use all 24 logical CPUs and
about half of the 91.5 GB of RAM. The Ubuntu ext4.vhdx is 14.1 GB and lives on
C:, which has 94.7 GB free. The E: archive disk has 733 GB free; D: has 121 GB.

## Recommended .wslconfig

    [wsl2]
    processors=12
    memory=48GB
    swap=8GB
    networkingMode=mirrored
    firewall=true
    dnsTunneling=true

Rationale:

- The measured desktop slowdown comes from WSL2 claiming every logical CPU.
  Capping at 12 leaves one core group for interactive use.
- 48 GB leaves roughly 43 GB for Windows while still covering the measured peak
  commit of the audit and repair stages.
- These are interactive-profile values. Before a batch or overnight run the
  limits can be raised, and the parallel runner profiles already refuse to
  oversubscribe whatever the host reports.

## Scratch volume

/scratch needs a Linux-native ext4 filesystem. The existing distro vhdx is too
small, so the intended step is a dedicated dynamic VHDX on D: (about 80 GB)
mounted at /scratch. That requires a manual mount step and an /etc/fstab entry;
it is deliberately not automated here, and preflight() refuses a scratch root
while /scratch is absent.

## Not recommended

- Do not move the project to /mnt/c or /mnt/e for computation.
- Do not raise write timeouts to work around the 9p bridge; move the I/O.
