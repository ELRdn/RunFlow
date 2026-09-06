import os
import re
import subprocess
from pathlib import Path

from .core import digest, file_hash, read, write
from .contracts import validate

SCRIPT = r'''set -eo pipefail
case_dir=$1
test -f /opt/openfoam14/etc/bashrc || { echo "OpenFOAM Foundation 14 is missing"; exit 2; }
source /opt/openfoam14/etc/bashrc
test "$WM_PROJECT_VERSION" = 14 || exit 2
test -d "$case_dir" && test ! -e "$case_dir/case" || exit 2
cp -r "$FOAM_TUTORIALS/incompressibleFluid/cylinder" "$case_dir/case"
cd "$case_dir/case"
dpkg-query -W -f='${Version}\n' openfoam14 > ../solver-version.txt
test "$(cat ../solver-version.txt)" = 20260724 || { echo "OpenFOAM package pin mismatch"; exit 2; }
find 0 constant system -type f -print0 | sort -z | xargs -0 sha256sum > ../input-files.sha256
blockMesh > ../blockMesh.log 2>&1
mirrorMesh > ../mirrorMesh.log 2>&1
checkMesh > ../checkMesh.log 2>&1
grep -q 'Mesh OK' ../checkMesh.log
foamRun > ../foamRun.log 2>&1
grep -q '^End' ../foamRun.log
'''


def force_rows(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        tokens = re.sub(r"[()]", " ", line).split()
        values = [float(token) for token in tokens]
        import math
        if len(values) < 7 or not all(math.isfinite(v) for v in values):
            raise ValueError("Invalid or non-finite force history")
        rows.append(values)
    if len(rows) < 2 or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("Force history must have multiple increasing timestamps")
    return rows


def reynolds(case):
    import math
    def number(file, key):
        text = (Path(case)/file).read_text()
        found = re.findall(r"^\s*"+key+r"\s+([0-9.eE+-]+)\s*;",text,re.M)
        if len(found) != 1:
            raise ValueError("Cannot resolve baseline parameter: "+key)
        value=float(found[0])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Invalid baseline parameter: "+key)
        return value
    values = {"diameter_m":number("system/blockMeshDict","diameter"),
              "inlet_speed_m_s":number("0/U","Uinlet"),
              "kinematic_viscosity_m2_s":number("constant/physicalProperties","nu")}
    values["Re"] = values["inlet_speed_m_s"]*values["diameter_m"]/values["kinematic_viscosity_m2_s"]
    if not math.isclose(values["Re"],1,rel_tol=1e-10):
        raise ValueError("Baseline case does not have Re=1")
    return values


def run(output, distro="Ubuntu", timeout_s=1800):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)  # fresh case only: never accept old solver output
    pending = {"schema_version": "1", "experiment_id": "rf-baseline-"+digest({"state":"pending","runner":SCRIPT}),
          "execution_status": "BLOCKED", "scientific_status": "PENDING_HUMAN_REVIEW",
          "ranking_eligible": False, "drag_N": None, "Cd": None, "CdA_m2": None,
          "notes": ["Baseline not finished"]}
    write(output / "result.json", pending)
    try:
        if os.name == "nt":
            converted = subprocess.run(["wsl", "-d", distro, "--", "wslpath", "-a", output.as_posix()],
                                       check=True, capture_output=True, text=True, timeout=30).stdout.strip()
            command = ["wsl", "-d", distro, "--", "timeout", "--kill-after=10", str(timeout_s), "bash", "-s", "--", converted]
        else:
            command = ["timeout", "--kill-after=10", str(timeout_s), "bash", "-s", "--", str(output)]
        with (output / "launcher.log").open("wb") as log:
            subprocess.run(command, input=SCRIPT.encode("utf-8"), stdout=log, stderr=subprocess.STDOUT,
                           timeout=timeout_s+30, check=True)
        forces = sorted((output / "case" / "postProcessing").rglob("forces.dat"))
        if not forces:
            # Foundation force function object may name its file force.dat.
            forces = sorted((output / "case" / "postProcessing").rglob("force.dat"))
        if len(forces) != 1:
            raise ValueError(f"Expected one force history, found {len(forces)}")
        rows = force_rows(forces[0])
        inputs = {"solver_package": (output / "solver-version.txt").read_text().strip(),
                  "tutorial": "incompressibleFluid/cylinder", **reynolds(output/"case"),
                  "input_files": (output / "input-files.sha256").read_text().splitlines(),
                  "runner_sha256": digest(SCRIPT)}
        identity = "rf-baseline-" + digest(inputs)
        validate("baseline-config",inputs)
        write(output / "config.json", inputs)
        history = {"rows": rows, "source_sha256": file_hash(forces[0]),
                   "note": "Raw upstream force columns; see source header"}
        validate("force-history",history)
        write(output / "force-history.json", history)
        result = {"schema_version": "1", "experiment_id": identity, "execution_status": "PASS",
                  "scientific_status": "PENDING_HUMAN_REVIEW", "ranking_eligible": False,
                  "drag_N": None, "Cd": None, "CdA_m2": None,
                  "notes": ["Cylinder Re=1 execution smoke only; not human aerodynamic validation",
                            f"Finite force rows: {len(rows)}"]}
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result = dict(pending)
        result["execution_status"] = "FAIL"
        result["notes"] = [str(error)]
    validate("result", result)
    write(output / "result.json", result)
    log = {"schema_version": "1", "task_id": "baseline", "experiment_id": result["experiment_id"],
           "agent": "runflow", "actions": ["copy cylinder", "blockMesh", "mirrorMesh", "checkMesh", "foamRun", "parse forces"],
           "files_changed": [p.name for p in output.iterdir() if p.is_file()], "parameters_changed": [],
           "errors": [] if result["execution_status"] == "PASS" else result["notes"], "validation_pending": True}
    validate("log", log)
    write(output / "task-log.json", log)
    return result
