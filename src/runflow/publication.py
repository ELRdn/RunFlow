"""Produce numeric summaries only. Never recursively copy an input directory."""
from pathlib import Path
from .contracts import validate
from .core import write


def public_result(result, output):
    validate("result", result)
    # Do not copy notes: free text could contain local paths or protected data.
    safe = {key: result[key] for key in ("schema_version", "experiment_id", "execution_status",
            "scientific_status", "ranking_eligible", "drag_N", "Cd", "CdA_m2")}
    output = Path(output)
    validate("public-summary",safe)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "summary.json", safe)
    return safe
