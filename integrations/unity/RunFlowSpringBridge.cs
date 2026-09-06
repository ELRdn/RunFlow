using System;
using UnityEngine;

namespace RunFlow
{
    // Requires the hash-checked DynamicBone patch. Explicit order is part of capture configuration.
    public sealed class RunFlowSpringBridge : MonoBehaviour
    {
        public DynamicBone[] springs;
        public void Begin()
        {
            if (springs == null || springs.Length == 0) throw new InvalidOperationException("Explicit spring array required");
            var seen = new System.Collections.Generic.HashSet<DynamicBone>();
            foreach (var spring in springs)
                if (spring == null || !seen.Add(spring)) throw new InvalidOperationException("Missing or duplicate spring");
            try { foreach (var spring in springs) spring.RunFlowBegin(); }
            catch { End(); throw; }
        }
        public void BeforeAnimation() { foreach (var spring in springs) spring.RunFlowBeforeAnimation(); }
        public void Step(float dt) { foreach (var spring in springs) spring.RunFlowStep(dt); }
        public void End() { if (springs != null) foreach (var spring in springs) if (spring != null) spring.RunFlowEnd(); }
        void OnDisable() { End(); }
    }
}
