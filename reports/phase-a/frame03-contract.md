# Phase A5 - frame-03 projection contract

2026-09-13.

## Problem

frame-03 reached a valid geometry result but could not enter CFD. The audit
left two artifacts:

- projections.json, complete = false, containing front and side only (the top
  view hit the 3,660 s stage guard)
- projections-merged.json, complete = true, containing all three views

CFD admission required projections.json with complete = true, so a metadata
split - not a geometry failure - blocked the frame.

## Contract now enforced

The authoritative artifact is projections.json holding exactly the three
canonical views (front, side, top) with complete = true. Validation checks
completeness, the exact view set, finite positive source and candidate areas,
a finite non-negative area difference, an IoU within [0, 1], and that each
view's axes match its canonical plane.

The legacy split form stays admissible for existing results, but only when the
merged document passes the same validation and every input hash it records
still matches the file on disk. A missing, unreadable, hash-mismatched, or
incomplete merged document is rejected, so a merged artifact can never mask an
actually incomplete audit.

## Promotion

scripts/promote_projection_audit.py rewrites projections.json from evidence
that is already valid. It never recomputes a projection and never deletes the
earlier bytes:

- the previous projections.json is archived as projections-prior.json
- the promotion block records the prior hashes and the evidence hashes
- a second promotion is a no-op because the canonical file already validates

## Result for frame-03

The pre-existing evidence was promoted without recomputation:

- prior projections.json: c171aa1c5f1e548142fcd3659d32d5864c84879c4bfe0fb39a93a1eb69bc5770
- evidence: projections-merged.json cd3de205b3d597ebbdd95d1323f7b0d7c675b2155d7947ace50a2f3cc0021634
  with inputs projections.json (same prior hash) and projection-top.json
  2186f0dbd6cf2e9d57a608008ac5d3f9a340511710e2207e86e9aa4eb85f7f21
- canonical projections.json after promotion:
  66dea7709d6b65f89b69f338e445aaa24ade8dd6ebd30ddb7248ca47eaf2faee

Before promotion the --check mode already reported projections-merged.json as
the authoritative artifact, which is what unblocked admission. After promotion
the canonical file is authoritative.

No projection was recomputed, no threshold was changed, and no previous
artifact was deleted.

## Tests

tests/test_phase_a.py covers: canonical preferred over merged; verified merged
accepted; missing, corrupt, or hash-mismatched merged rejected; neither valid
rejected; promotion from per-view files; promotion from a merged artifact with
prior archival; promotion idempotence.
