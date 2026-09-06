"""Produce a narrowly patched copy of the exact upstream DynamicBone source.

Never edits the upstream checkout. Apply the output in a private Unity project.
Normal playback still supplies Time.deltaTime. Manual capture supplies explicit dt.
"""
import argparse
from pathlib import Path
from runflow.core import file_hash, write

UPSTREAM_SHA256="8a2ce23a4e3b5fc4ed1d22d6116be87b58a75bc7f77b704d62da6e1eda0afbe3"
COMMIT="d50b28379337b507751a7df705a10afeab2c37ce"
API='''
    // RunFlow: explicit stepping for a dedicated capture scene only.
    public bool RunFlowManualMode { get; private set; }
    public void RunFlowBegin()
    {
        if (m_DistantDisable) throw new System.InvalidOperationException("Disable camera-distance culling explicitly for capture");
        if (Particles.Count == 0) throw new System.InvalidOperationException("Initialize source springs before capture");
        RunFlowManualMode = true;
        InitTransforms();
        m_Time = 0;
        m_DistantDisabled = false;
        m_ObjectMove = Vector3.zero;
        ResetParticlesPosition();
    }
    public void RunFlowBeforeAnimation()
    {
        if (!RunFlowManualMode) throw new System.InvalidOperationException("RunFlowBegin required");
        PreUpdate();
    }
    public void RunFlowStep(float dt)
    {
        if (!RunFlowManualMode || dt <= 0 || float.IsNaN(dt) || float.IsInfinity(dt))
            throw new System.InvalidOperationException("Invalid explicit spring step");
        if (m_Weight > 0) UpdateDynamicBones(dt);
    }
    public void RunFlowEnd() { RunFlowManualMode = false; }
'''


def patch(source):
    def replace_once(old,new):
        nonlocal source
        if source.count(old)!=1:raise ValueError("Pinned source structure mismatch")
        source=source.replace(old,new,1)
    replace_once("public class DynamicBone : MonoBehaviour\n{","public class DynamicBone : MonoBehaviour\n{"+API)
    for name in ["FixedUpdate","Update","LateUpdate"]:
        replace_once("void "+name+"()\n    {","void "+name+"()\n    {\n        if (RunFlowManualMode) return;")
    replace_once("timeVar = Time.deltaTime * m_UpdateRate;","timeVar = t * m_UpdateRate;")
    replace_once("timeVar = Time.deltaTime;","timeVar = t;")
    return source


def main():
    p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    if file_hash(a.source)!=UPSTREAM_SHA256:raise ValueError("Wrong upstream DynamicBone source hash")
    text=patch(a.source.read_text(encoding="utf-8-sig"))
    a.output.mkdir(parents=True,exist_ok=False)
    target=a.output/"DynamicBone.cs";target.write_text(text,encoding="utf-8",newline="\n")
    write(a.output/"patch-provenance.json",{"upstream_commit":COMMIT,"upstream_sha256":UPSTREAM_SHA256,
        "patched_sha256":file_hash(target),"runtime_verified":False,"scientific_status":"PENDING_HUMAN_REVIEW"})
    print("PATCH_PREPARED_RUNTIME_UNVERIFIED")


if __name__=="__main__":main()
