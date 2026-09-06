"""Compare evaluated RF-space geometry. No physics or mesh repair is performed."""
import math
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .contracts import JOINTS, validate
from .core import canonical, digest


def area(snapshot):
    canonical(snapshot)
    validate("snapshot", snapshot)
    vertices = snapshot["vertices"]
    polygons = []
    for tri in snapshot["triangles"]:
        if max(tri) >= len(vertices):
            raise ValueError("Triangle index outside vertex buffer")
        polygon = Polygon([(vertices[i][1], vertices[i][2]) for i in tri])
        if polygon.area > 0:
            polygons.append(polygon)
    value = unary_union(polygons).area
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Frontal area must be positive")
    return value


def compare(reference, candidate, height_m):
    if not math.isfinite(height_m) or height_m <= 0:
        raise ValueError("Invalid height")
    ra, ca = area(reference), area(candidate)
    if not math.isclose(reference["time_s"], candidate["time_s"], rel_tol=0, abs_tol=1e-7):
        raise ValueError("Snapshot times differ")
    if set(reference["joints"]) != set(candidate["joints"]):
        raise ValueError("Joint correspondence incomplete")
    errors = {name: math.dist(reference["joints"][name], candidate["joints"][name])
              for name in reference["joints"]}
    peak = max(errors.values())
    relative_area = abs(ca - ra) / ra
    report = {"reference_sha256": digest(reference), "candidate_sha256": digest(candidate),
            "time_s": reference["time_s"], "height_m": height_m,
            "max_joint_error_m": peak, "joint_errors_m": errors,
            "reference_area_m2": ra, "candidate_area_m2": ca,
            "relative_area_error": relative_area,
            "execution_status": "PASS" if peak <= 0.005*height_m and relative_area <= 0.01 else "FAIL",
            "scientific_status": "PENDING_HUMAN_REVIEW", "ranking_eligible": False}
    validate("comparison",report)
    return report


def verify_gait(manifest, reference_dir, candidate_dir, repeat_dir):
    from pathlib import Path
    from .core import read, sample
    expected = sample(manifest)["samples"]
    def frames(directory):
        values = [read(p) for p in Path(directory).glob("*.snapshot.json")]
        if len(values) != 16:
            raise ValueError("A gait verification requires exactly 16 snapshots per directory")
        values.sort(key=lambda v:v["time_s"])
        for value, stamp in zip(values,expected):
            if not math.isclose(value["time_s"],stamp["time_s"],rel_tol=0,abs_tol=1e-7):
                raise ValueError("Capture timestamps differ from experiment sampling")
        return values
    reference,candidate,repeat = map(frames,(reference_dir,candidate_dir,repeat_dir))
    comparisons = [compare(r,c,manifest["height_m"]) for r,c in zip(reference,candidate)]
    repeated = []
    for first,second in zip(reference,repeat):
        validate("snapshot", second)
        repeated.append(digest(first) == digest(second))
    report = {"schema_version":"1","comparisons":comparisons,"reference_repeat_identical":repeated,
            "execution_status":"PASS" if all(repeated) and all(r["execution_status"] == "PASS" for r in comparisons) else "FAIL",
            "scientific_status":"PENDING_HUMAN_REVIEW","ranking_eligible":False,
            "note":"Part presence requires recorded human inspection; numeric checks alone do not approve official fidelity"}
    validate("gait-verification",report)
    return report
