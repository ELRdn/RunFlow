"""Pure motion-catalog classification for RunFlow Phase 0.

This module only sorts and labels motion-catalog records with filename
heuristics. It performs no canonical verification, reads no game data,
hashes no content, and grants no scientific approval.

Input: an iterable of dicts. Each record uses:
  path: actual 3d/motion path, required. The keys source_path and
    full_path are accepted as aliases when path is absent.
  asset_hash: optional passthrough string (sha256 accepted as alias).
  prerequisites: optional list of prerequisite path strings
    (requires accepted as alias; a single string is wrapped).

Output: list of dicts sorted by normalized source_path, deduplicated
on the full normalized path. Identical repeats dedupe deterministically
(first kept); same path with conflicting normalized hash or prerequisites
raises. Every record is validated before dedupe so a malformed repeat is
never silently ignored. Each item has:
  source_path, asset_hash, prerequisites,
  ui_generic_eligible, ui_generic_reason,
  target, body_motion_candidate,
  name_heuristics, categories, signals,
  verified (always False),
  scientific_status (always PENDING_HUMAN_REVIEW),
  ranking_eligible (always False),
  notes.

Rules (heuristic only, see function docstrings):
  Unity viewer generic eligibility: positive when the lowercased path
    contains '/type0', '/type99' or 'anm_sty_', unless excluded by
    'mini', 'facial', '_cam', 'mirror', stem endings '_s' / '_e' /
    '_pos' / '_pose', '/tail', 'prop' or '_defaultmotion'. Viewer-list
    placement only, never scientific validity. The '/type0' substring
    also matches '/type01' to '/type04' paths; this is viewer placement
  only and never maps type numbers to characters.
  Target: 'character:1006' for contiguous chara1006, chr1006 or
    character1006 with a trailing numeric boundary (chr10060 does not
    match) overrides 'card-body:1006' for contiguous card1006, body1006
    or crd1006 with the same boundary. Bare 1006, split words such as
    body slash 1006, or loose chara or body words elsewhere never bind.
    Database fields such as race running type are never auto-mapped to
    a target. Filename labels stay heuristic only.
  Body candidacy: body/race/run/locomotion filename signals count even
    when the record is not UI-generic, but any eye/ear/tail/face signal
    vetoes candidacy so part-only clips are never promoted. Overrun is
    separate from ordinary run and also vetoes candidacy.
  Eye/ear/tail/face, live/event/skill and base/start/last_spurt/
    overlay plus racemain/default/pitch/stride/overrun context markers
    are reported as NAME_HEURISTIC filename hints only. The racemain
    _default base family lives outside the generic filter and surfaces
    through body candidacy. A _default directory is distinct from the
    _defaultmotion exclusion.
  Unknown is preserved and no motion or clip IDs are invented.

Local DB reading and result integration belong to the parent caller;
this module deliberately duplicates neither. Tests use synthetic path
strings only and read no live catalog.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["classify"]

SCIENTIFIC_STATUS = "PENDING_HUMAN_REVIEW"

_TARGET_CHARACTER = "character:1006"
_TARGET_CARD_BODY = "card-body:1006"
_TARGET_UNKNOWN = "unknown"

_BODY_VARIANTS = ("bodies",)
_FACE_VARIANTS = ("facial",)
_RUN_VARIANTS = ("running",)
_START_VARIANTS = ("starting",)

_NOTES = [
    "UI generic eligibility describes viewer-list placement only, not scientific validity.",
    "Name heuristics are filename-only hints, never verified. Unknown is preserved and no IDs are invented.",
    "Racemain default base family is outside the generic filter and surfaces through body candidacy. Overrun is separate from run. Type numbers and race running type are never auto-mapped.",
    "Target needs a contiguous marker with trailing numeric boundary. Duplicate paths with conflicting hash or prerequisites raise.",
]


def _tokens(lower):
    """Split lowercased text into ascii-alphanumeric tokens."""
    parts = []
    current = []
    for char in lower:
        if char.isascii() and char.isalnum():
            current.append(char)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return parts


def _token_hit(tokens, key, variants=()):
    """Match a whole token, its plural, a variant, or key+digits."""
    for token in tokens:
        if token == key or token in variants:
            return True
        if token == key + "s":
            return True
        if token.startswith(key) and len(token) > len(key) and token[len(key)].isdigit():
            return True
    return False


def _normalize_path(value, index):
    """Normalize separators; reject missing or NUL-containing paths."""
    if not isinstance(value, str):
        raise ValueError("record " + str(index) + ": path must be a string")
    text = value.strip().replace(chr(92), "/")
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) > 1:
        text = text.rstrip("/")
    if not text or text == "/":
        raise ValueError("record " + str(index) + ": missing path")
    if chr(0) in text:
        raise ValueError("record " + str(index) + ": path contains NUL")
    return text


def _stem_of(normalized):
    """Filename without directory prefix or extension."""
    base = normalized.rsplit("/", 1)[-1]
    if "." in base and not base.startswith("."):
        return base.rsplit(".", 1)[0]
    return base


def _ui_generic(lower, stem_lower):
    """Viewer-list eligibility: positive markers minus exclusions.

    Positive when the lowercased path contains '/type0', '/type99' or
    'anm_sty_'. Excluded by 'mini', 'facial', '_cam', 'mirror', stem
    endings '_s' / '_e' / '_pos' / '_pose', '/tail', 'prop' or
    '_defaultmotion'. The '/type01' to '/type04' family matches '/type0'
    by substring; this is viewer placement only. A '_default' directory
    is distinct from the '_defaultmotion' exclusion.
    """
    has_type0 = "/type0" in lower
    has_type99 = "/type99" in lower
    has_anm = "anm_sty_" in lower
    positive = has_type0 or has_type99 or has_anm
    excluded = {}
    excluded["mini"] = "mini" in lower
    excluded["facial"] = "facial" in lower
    excluded["cam"] = "_cam" in lower
    excluded["mirror"] = "mirror" in lower
    excluded["ending"] = stem_lower.endswith(("_s", "_e", "_pos", "_pose"))
    excluded["tail"] = "/tail" in lower
    excluded["prop"] = "prop" in lower
    excluded["defaultmotion"] = "_defaultmotion" in lower
    hits = sorted(name for name, flag in excluded.items() if flag)
    if not positive:
        reason = "no-positive-marker"
    elif hits:
        reason = "excluded:" + "+".join(hits)
    else:
        reasons = []
        if has_type0:
            reasons.append("type0")
        if has_type99:
            reasons.append("type99")
        if has_anm:
            reasons.append("anm_sty")
        reason = "positive:" + "+".join(reasons)
    return positive and not hits, reason, has_type0, has_type99, has_anm, excluded

def _bound_present(lower, needle):
    start = 0
    while True:
        idx = lower.find(needle, start)
        if idx < 0:
            return False
        end = idx + len(needle)
        if end >= len(lower):
            return True
        nxt = lower[end]
        if nxt < "0" or nxt > "9":
            return True
        start = idx + 1


def _target(lower, tokens):
    """Resolve 1006 affinity; character evidence overrides card-body.

    Only contiguous chara1006, chr1006 or character1006 binds character,
    and only contiguous card1006, body1006 or crd1006 binds card-body.
    Each match needs a trailing numeric boundary, so chr10060 never binds.
    Bare 1006, split body slash 1006, and loose words elsewhere never bind.
    Type numbers and race running type fields are never auto-mapped.
    Labels stay filename heuristics with verified False and pending review.
    """
    has_1006 = "1006" in lower
    chara_bound = _bound_present(lower, "chara1006") or _bound_present(lower, "chr1006") or _bound_present(lower, "character1006")
    card_bound = _bound_present(lower, "card1006") or _bound_present(lower, "body1006") or _bound_present(lower, "crd1006")
    chara_hint = bool(chara_bound)
    card_body_hint = bool(card_bound)
    character_explicit = bool(_bound_present(lower, "character1006"))
    if chara_bound:
        return _TARGET_CHARACTER, has_1006, chara_hint, card_body_hint, character_explicit
    if card_bound:
        return _TARGET_CARD_BODY, has_1006, chara_hint, card_body_hint, character_explicit
    return _TARGET_UNKNOWN, has_1006, chara_hint, card_body_hint, character_explicit


def _name_hints(lower, tokens):
    """Filename-only hints; never a verification of clip content.

    Racemain, default, pitch, stride and overrun are context markers
    only and never grant candidacy. Overrun never sets the run hint
    because matching is whole-token plus digits. A defaultmotion token
    never sets the default hint.
    """
    hints = {}
    hints["eye"] = _token_hit(tokens, "eye")
    hints["ear"] = _token_hit(tokens, "ear")
    hints["tail"] = _token_hit(tokens, "tail") or ("/tail" in lower)
    hints["face"] = _token_hit(tokens, "face", _FACE_VARIANTS) or ("facial" in lower)
    hints["live"] = _token_hit(tokens, "live")
    hints["event"] = _token_hit(tokens, "event")
    hints["skill"] = _token_hit(tokens, "skill")
    hints["base"] = _token_hit(tokens, "base")
    hints["start"] = _token_hit(tokens, "start", _START_VARIANTS)
    hints["last_spurt"] = ("last_spurt" in lower) or ("lastspurt" in lower) or ("last" in tokens and "spurt" in tokens)
    hints["overlay"] = _token_hit(tokens, "overlay")
    hints["body"] = _token_hit(tokens, "body", _BODY_VARIANTS)
    hints["race"] = _token_hit(tokens, "race")
    hints["run"] = _token_hit(tokens, "run", _RUN_VARIANTS)
    hints["locomotion"] = any("locomot" in token for token in tokens)
    hints["racemain"] = _token_hit(tokens, "racemain")
    hints["default"] = _token_hit(tokens, "default")
    hints["pitch"] = _token_hit(tokens, "pitch")
    hints["stride"] = _token_hit(tokens, "stride")
    hints["overrun"] = _token_hit(tokens, "overrun")
    return hints


def _classify_one(source_path, asset_hash, prerequisites):
    """Build one stable, always-unverified classification record.

    Body candidacy needs body, race, run or locomotion hints without any
    eye, ear, tail, face or overrun hint. Racemain, default, pitch,
    stride and overrun stay heuristic-only.
    """
    lower = source_path.lower()
    tokens = _tokens(lower)
    stem_lower = _stem_of(lower)
    eligible, reason, has_type0, has_type99, has_anm, excluded = _ui_generic(lower, stem_lower)
    target, has_1006, chara_hint, card_body_hint, character_explicit = _target(lower, tokens)
    hints = _name_hints(lower, tokens)
    part_only = hints["eye"] or hints["ear"] or hints["tail"] or hints["face"]
    locomotion_like = hints["body"] or hints["race"] or hints["run"] or hints["locomotion"]
    overrun_hint = hints["overrun"]
    body_candidate = bool(locomotion_like and not part_only and not overrun_hint)
    name_heuristics = sorted(name for name, flag in hints.items() if flag)
    categories = ["ui_generic_eligible" if eligible else "ui_generic_excluded", "target:" + target]
    if body_candidate:
        categories.append("body_motion_candidate")
    for name in name_heuristics:
        categories.append("name_heuristic:" + name)
    if not name_heuristics and not body_candidate:
        categories.append("unknown")
    categories = sorted(set(categories))
    signals = {
        "has_type0": has_type0,
        "has_type99": has_type99,
        "has_anm_sty": has_anm,
        "excluded_mini": excluded["mini"],
        "excluded_facial": excluded["facial"],
        "excluded_cam": excluded["cam"],
        "excluded_mirror": excluded["mirror"],
        "excluded_ending": excluded["ending"],
        "excluded_tail": excluded["tail"],
        "excluded_prop": excluded["prop"],
        "excluded_defaultmotion": excluded["defaultmotion"],
        "ui_generic_eligible": eligible,
        "has_1006": has_1006,
        "chara_hint": chara_hint,
        "card_body_hint": card_body_hint,
        "character_explicit": character_explicit,
        "is_target_1006": target != _TARGET_UNKNOWN,
        "body_motion_candidate": body_candidate,
        "name_eye": hints["eye"],
        "name_ear": hints["ear"],
        "name_tail": hints["tail"],
        "name_face": hints["face"],
        "name_live": hints["live"],
        "name_event": hints["event"],
        "name_skill": hints["skill"],
        "name_base": hints["base"],
        "name_start": hints["start"],
        "name_last_spurt": hints["last_spurt"],
        "name_overlay": hints["overlay"],
        "name_body": hints["body"],
        "name_race": hints["race"],
        "name_run": hints["run"],
        "name_locomotion": hints["locomotion"],
        "name_racemain": hints["racemain"],
        "name_default": hints["default"],
        "name_pitch": hints["pitch"],
        "name_stride": hints["stride"],
        "name_overrun": hints["overrun"],
    }
    return {
        "source_path": source_path,
        "asset_hash": asset_hash,
        "prerequisites": list(prerequisites),
        "ui_generic_eligible": eligible,
        "ui_generic_reason": reason,
        "target": target,
        "body_motion_candidate": body_candidate,
        "name_heuristics": name_heuristics,
        "categories": categories,
        "signals": signals,
        "verified": False,
        "scientific_status": SCIENTIFIC_STATUS,
        "ranking_eligible": False,
        "notes": list(_NOTES),
    }


def classify(records):
    """Classify motion-catalog records without verifying them.

    Sorting and deduplication use the full normalized path, so equal
    basenames in different directories are preserved. Identical repeats
    dedupe deterministically with the first kept. Same path with different
    normalized hash or prerequisites raises. Prerequisites compare
    order-sensitively after stripping. Every record is validated before
    dedupe so a malformed repeat is never silently ignored. Output order
    is sorted by source_path and is stable for equal inputs. The racemain
    default base family is classified as body candidates even when it
    sits outside the generic filter. Overrun never counts as run, and
    type numbers plus race running type never map to a target.
    """
    if isinstance(records, (str, bytes)) or not isinstance(records, Iterable):
        raise ValueError("records must be an iterable of dicts")
    parsed = []
    for order_index, item in enumerate(records):
        if not isinstance(item, Mapping):
            raise ValueError("record " + str(order_index) + ": must be a mapping")
        if "path" in item:
            raw_path = item["path"]
        elif "source_path" in item:
            raw_path = item["source_path"]
        elif "full_path" in item:
            raw_path = item["full_path"]
        else:
            raise ValueError("record " + str(order_index) + ": missing path")
        source_path = _normalize_path(raw_path, order_index)
        if "asset_hash" in item:
            raw_hash = item["asset_hash"]
        else:
            raw_hash = item.get("sha256")
        if raw_hash is None:
            asset_hash = None
        elif isinstance(raw_hash, str):
            asset_hash = raw_hash.strip() or None
            if asset_hash is not None and chr(0) in asset_hash:
                raise ValueError("record " + str(order_index) + ": asset_hash contains NUL")
        else:
            raise ValueError("record " + str(order_index) + ": asset_hash must be a string or null")
        if "prerequisites" in item:
            raw_pre = item["prerequisites"]
        else:
            raw_pre = item.get("requires", [])
        if raw_pre is None:
            prereqs = []
        elif isinstance(raw_pre, str):
            cleaned = raw_pre.strip()
            if chr(0) in cleaned:
                raise ValueError("record " + str(order_index) + ": prerequisites contain NUL")
            prereqs = [cleaned] if cleaned else []
        elif isinstance(raw_pre, (list, tuple)):
            prereqs = []
            for pos, entry in enumerate(raw_pre):
                if not isinstance(entry, str):
                    raise ValueError("record " + str(order_index) + ": prerequisites must be strings")
                cleaned = entry.strip()
                if cleaned:
                    if chr(0) in cleaned:
                        raise ValueError("record " + str(order_index) + ": prerequisites contain NUL")
                    prereqs.append(cleaned)
        else:
            raise ValueError("record " + str(order_index) + ": prerequisites must be a list of strings")
        parsed.append((source_path, asset_hash, prereqs))
    seen = {}
    for source_path, asset_hash, prereqs in parsed:
        if source_path not in seen:
            seen[source_path] = (asset_hash, prereqs)
        else:
            prev_hash, prev_pre = seen[source_path]
            if prev_hash != asset_hash or prev_pre != prereqs:
                raise ValueError("duplicate path with conflicting hash or prerequisites: " + source_path)
    results = [_classify_one(path, pair[0], pair[1]) for path, pair in seen.items()]
    results.sort(key=lambda record: record["source_path"])
    return results
