// RunFlow Phase-0 capture helper (Unity 2022.3, standalone, no packages, no Editor API).
// Pinned UmaViewer source only. This file provides NO model, motion, or official asset.
// What it does: steps an explicitly configured Animator at a fixed dt, bakes the
// visible body geometry under a user-configured root, transforms it into the
// RunFlow frame (RF_X_FORWARD_Z_UP, metres), and writes per-frame OBJ +
// snapshot JSON + provenance sidecar to a user-designated directory.
// Physics limit (do NOT overclaim): capture only calls Animator.Update with a fixed
// step. Unity Animator playback is NOT a deterministic spring simulation. Hair /
// tail / costume spring motion from UmaViewer is only captured when the user wires
// the real UmaViewer spring-stepping call into onStepUmaViewerSprings AND sets
// hasVerifiedSpringIntegration = true. Otherwise CaptureSequence aborts.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;
using UnityEngine.Events;

namespace RunFlow
{
    [DisallowMultipleComponent]
    [AddComponentMenu("RunFlow/RunFlowCapture")]
    public sealed class RunFlowCapture : MonoBehaviour
    {
        public const string SnapshotSchemaVersion = "1";
        public const string RfCoordinateSystem = "RF_X_FORWARD_Z_UP";
        public const string RfUnit = "m";

        static readonly HashSet<string> AllowedParts = new HashSet<string>(StringComparer.Ordinal)
        {
            "head", "torso", "left_arm", "right_arm", "left_leg", "right_leg",
            "ears", "hair", "tail", "costume"
        };

        [Serializable]
        public struct JointBinding
        {
            public string semanticName;
            public Transform source;
        }

        [Header("Pinned source (configure explicitly, nothing is guessed)")]
        public Animator animator;
        public Transform root;
        public Transform trajectoryRoot;
        public AnimationClip clip;
        public string animatorStateName;

        [Header("Fixed-time sequence")]
        [Min(1)] public int frameCount = 16;
        [Min(1f)] public float fps = 60f;
        [Min(0f)] public float warmupSeconds = 0.5f;
        [Min(1)] public int simulationStepsPerSample = 4;
        public bool allowLoopBeyondClipLength;

        [Header("Source -> RF transform (required, no default assumption)")]
        public Matrix4x4 sourceToRf = Matrix4x4.identity;
        public bool sourceToRfConfigured;
        public float rfScale = 1f;

        [Header("Semantic joints (explicit only, never auto-mapped)")]
        public List<JointBinding> joints = new List<JointBinding>();

        [Header("Semantic parts present in this capture")]
        public List<string> includedParts = new List<string>();
        public string partsReviewReference;
        public bool diagnosticOnly;

        [Header("UmaViewer spring integration hook (required)")]
        public bool hasVerifiedSpringIntegration;
        public UnityEvent<float> onStepUmaViewerSprings = new UnityEvent<float>();
        public UnityEvent onResetUmaViewerSprings = new UnityEvent();
        public UnityEvent onBeforeAnimation = new UnityEvent();
        public UnityEvent onFinish = new UnityEvent();
        public UnityEvent<float> onAfterAnimation = new UnityEvent<float>();

        [Header("Private output (user-designated only)")]
        public string outputDirectory = "";
        public string baseName = "runflow_capture";

        static string FullPath(Transform t)
        {
            var stack = new Stack<string>();
            for (var c = t; c != null; c = c.parent) stack.Push(c.name);
            return string.Join("/", stack);
        }

        static string F(float v) { if (!IsFinite(v)) throw new InvalidOperationException("Non-finite capture"); return v.ToString("R", CultureInfo.InvariantCulture); }
        static string Fd(double v) { if (double.IsNaN(v) || double.IsInfinity(v)) throw new InvalidOperationException("Non-finite time"); return v.ToString("R", CultureInfo.InvariantCulture); }

        static string JsonStr(string s)
        {
            var sb = new StringBuilder(s.Length + 2);
            sb.Append('"');
            foreach (var ch in s)
            {
                if (ch == '"') sb.Append("\\\"");
                else if (ch == '\\') sb.Append("\\\\");
                else if (ch == '\n') sb.Append("\\n");
                else if (ch == '\r') sb.Append("\\r");
                else if (ch == '\t') sb.Append("\\t");
                else if (ch < 0x20) sb.Append("\\u").Append(((int)ch).ToString("x4"));
                else sb.Append(ch);
            }
            sb.Append('"');
            return sb.ToString();
        }

        static bool IsFinite(float v) { return !(float.IsNaN(v) || float.IsInfinity(v)); }

        void Validate()
        {
            if (animator == null) throw new InvalidOperationException("RunFlowCapture: animator is not assigned.");
            if (animator.cullingMode != AnimatorCullingMode.AlwaysAnimate)
                throw new InvalidOperationException("AlwaysAnimate is required for offline capture.");
            if (root == null) throw new InvalidOperationException("RunFlowCapture: root is not assigned.");
            if (clip == null) throw new InvalidOperationException("RunFlowCapture: clip is not assigned.");
            if (string.IsNullOrWhiteSpace(animatorStateName)) throw new InvalidOperationException("Explicit controller state required; UmaViewer uses motion_2, not the clip filename.");
            if (animator.runtimeAnimatorController == null)
                throw new InvalidOperationException("RunFlowCapture: animator has no RuntimeAnimatorController. Put the pinned clip in a state and retry.");
            if (frameCount != 16 || simulationStepsPerSample < 1) throw new InvalidOperationException("RunFlowCapture: 16 samples and positive simulationStepsPerSample required.");
            if (fps <= 0f || !IsFinite(fps)) throw new InvalidOperationException("RunFlowCapture: fps must be positive finite.");
            if (warmupSeconds < 0f || !IsFinite(warmupSeconds)) throw new InvalidOperationException("RunFlowCapture: warmupSeconds must be finite >= 0.");
            if (!sourceToRfConfigured) throw new InvalidOperationException("RunFlowCapture: sourceToRf is not configured. Set the explicit 4x4 source->RF matrix and tick sourceToRfConfigured. No axis/scale is assumed.");
            if (!IsFinite(rfScale) || rfScale <= 0f) throw new InvalidOperationException("RunFlowCapture: rfScale must be positive finite (source unit -> metres is explicit).");
            if (Math.Abs(sourceToRf.determinant) < 1e-12f) throw new InvalidOperationException("RunFlowCapture: sourceToRf is singular (determinant ~ 0).");
            if (!hasVerifiedSpringIntegration)
                throw new InvalidOperationException("RunFlowCapture: hasVerifiedSpringIntegration is FALSE. Wire the actual UmaViewer spring step to onStepUmaViewerSprings, verify it on this source, then opt in. Capture aborted so spring motion is never silently claimed as deterministic.");
            if (onStepUmaViewerSprings == null || onStepUmaViewerSprings.GetPersistentEventCount() == 0 || onResetUmaViewerSprings.GetPersistentEventCount() == 0 || onBeforeAnimation.GetPersistentEventCount() == 0)
                throw new InvalidOperationException("RunFlowCapture: actual spring reset AND step listeners are required.");
            if (onFinish == null || onFinish.GetPersistentEventCount() == 0)
                throw new InvalidOperationException("Spring release listener required, including failure cleanup.");
            if (!diagnosticOnly && string.IsNullOrWhiteSpace(partsReviewReference)) throw new InvalidOperationException("Part-presence review reference is required.");
            if (sourceToRf.GetRow(3) != new Vector4(0,0,0,1)) throw new InvalidOperationException("Transform must be affine.");
            for (int i=0; i<3; i++) for (int j=0; j<3; j++)
            {
                float dot=0; for (int k=0; k<3; k++) dot += sourceToRf[k,i]*sourceToRf[k,j];
                if (Mathf.Abs(dot-(i==j ? rfScale*rfScale : 0)) > 1e-6f*Mathf.Max(1,rfScale*rfScale))
                    throw new InvalidOperationException("Transform includes scale; rfScale is an assertion. No nonuniform scale or shear.");
            }
            if (joints == null || joints.Count == 0) throw new InvalidOperationException("RunFlowCapture: joints list is empty. Map every semantic joint explicitly; nothing is auto-mapped.");
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var j in joints)
            {
                if (string.IsNullOrWhiteSpace(j.semanticName)) throw new InvalidOperationException("RunFlowCapture: joint with empty semanticName.");
                if (j.source == null) throw new InvalidOperationException("RunFlowCapture: joint '" + j.semanticName + "' has no source Transform.");
                if (!seen.Add(j.semanticName.Trim())) throw new InvalidOperationException("RunFlowCapture: duplicate joint semanticName '" + j.semanticName + "'.");
            }
            if (includedParts == null || includedParts.Count == 0) throw new InvalidOperationException("RunFlowCapture: includedParts is empty.");
            var pseen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var p in includedParts)
            {
                if (!AllowedParts.Contains(p)) throw new InvalidOperationException("RunFlowCapture: unknown part '" + p + "'. Allowed: head, torso, left_arm, right_arm, left_leg, right_leg, ears, hair, tail, costume.");
                if (!pseen.Add(p)) throw new InvalidOperationException("RunFlowCapture: duplicate part '" + p + "'.");
            }
            if (!pseen.SetEquals(AllowedParts)) throw new InvalidOperationException("All required parts must be reviewed.");
            foreach (var required in new[] {"head","hip","left_hand","right_hand","left_knee","right_knee","left_foot","right_foot"})
                if (!seen.Contains(required)) throw new InvalidOperationException("Missing required joint: " + required);
            if (string.IsNullOrWhiteSpace(outputDirectory)) throw new InvalidOperationException("RunFlowCapture: outputDirectory is empty. Designate a private output directory.");
            if (string.IsNullOrWhiteSpace(baseName)) throw new InvalidOperationException("RunFlowCapture: baseName is empty.");
            if (Path.GetFileName(baseName) != baseName || baseName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
                throw new InvalidOperationException("baseName must be a filename, not a path.");
            double duration = (Mathf.RoundToInt(warmupSeconds * fps) + (frameCount - 1) * simulationStepsPerSample) / (double)fps;
            if (!allowLoopBeyondClipLength && duration > clip.length + 1e-4)
                throw new InvalidOperationException(string.Format(CultureInfo.InvariantCulture, "RunFlowCapture: sequence {0:F3}s exceeds clip '{1}' length {2:F3}s. Shorten the sequence or set allowLoopBeyondClipLength explicitly.", duration, clip.name, clip.length));
        }

        Vector3 ToRf(Vector3 world)
        {
            Vector3 p = sourceToRf.MultiplyPoint3x4(world);
            return p; // matrix already includes metres-per-source-unit
        }

        [ContextMenu("RunFlow: Capture Sequence")]
        public void CaptureSequence()
        {
            Validate();
            float dt = 1f / fps;
            string outDir = Path.IsPathRooted(outputDirectory)
                ? outputDirectory
                : Path.GetFullPath(Path.Combine(Application.dataPath, "..", outputDirectory));
            if (Directory.Exists(outDir)) throw new InvalidOperationException("Use a fresh capture output directory.");
            Directory.CreateDirectory(outDir);
            try
            {
            animator.Rebind();
            if (!animator.HasState(0, Animator.StringToHash(animatorStateName)))
                throw new InvalidOperationException("Configured controller state is missing.");
            try { animator.Play(animatorStateName, 0, 0f); }
            catch { throw new InvalidOperationException("RunFlowCapture: configured Animator state failed: " + animatorStateName); }
            animator.Update(0f);
            if (!animator.GetCurrentAnimatorClipInfo(0).Any(info => info.clip == clip))
                throw new InvalidOperationException("Controller state does not play the configured clip.");
            onResetUmaViewerSprings.Invoke();
            int warmupSteps = Mathf.RoundToInt(warmupSeconds * fps);
            onAfterAnimation.Invoke(0f);
            for (int w = 0; w < warmupSteps; w++) { onBeforeAnimation.Invoke(); animator.Update(dt); onAfterAnimation.Invoke(dt); onStepUmaViewerSprings.Invoke(dt); }
            bool haveRoot0 = false;
            Vector3 rfRoot0 = Vector3.zero;
            Vector3 srcRoot0 = Vector3.zero;
            for (int frame = 0; frame < frameCount; frame++)
            {
                if (frame > 0) for (int step=0; step<simulationStepsPerSample; step++) { onBeforeAnimation.Invoke(); animator.Update(dt); onAfterAnimation.Invoke(dt); onStepUmaViewerSprings.Invoke(dt); }
                double timeS = (warmupSteps + frame*simulationStepsPerSample) / (double)fps;
                CaptureOneFrame(outDir, frame, timeS, ref haveRoot0, ref rfRoot0, ref srcRoot0);
            }
            Debug.Log(string.Format(CultureInfo.InvariantCulture, "RunFlowCapture: wrote {0} frames to {1}", frameCount, outDir));
            }
            finally { onFinish.Invoke(); }
        }

        void CaptureOneFrame(string outDir, int frame, double timeS, ref bool haveRoot0, ref Vector3 rfRoot0, ref Vector3 srcRoot0)
        {
            var skins = root.GetComponentsInChildren<SkinnedMeshRenderer>(true)
                .Where(s => s != null && s.enabled && s.gameObject.activeInHierarchy)
                .OrderBy(s => FullPath(s.transform), StringComparer.Ordinal).ToList();
            var skinRoots = new HashSet<Transform>(skins.Select(s => s.transform));
            var filters = root.GetComponentsInChildren<MeshFilter>(true)
                .Where(mf => mf != null && mf.sharedMesh != null && mf.gameObject.activeInHierarchy && !skinRoots.Contains(mf.transform))
                .Where(mf => mf.GetComponent<MeshRenderer>() != null && mf.GetComponent<MeshRenderer>().enabled)
                .OrderBy(mf => FullPath(mf.transform), StringComparer.Ordinal).ToList();
            if (skins.Count == 0 && filters.Count == 0)
                throw new InvalidOperationException("RunFlowCapture: no bakeable SkinnedMeshRenderer/MeshFilter under root.");
            Vector3 srcRootWorld = (trajectoryRoot != null ? trajectoryRoot : root).position;
            Vector3 rfRoot = ToRf(srcRootWorld);
            if (!haveRoot0) { rfRoot0 = rfRoot; srcRoot0 = srcRootWorld; haveRoot0 = true; }
            Vector3 rfRootOut = rfRoot; // original trajectory retained in snapshot
            var verts = new List<Vector3>(8192);
            var tris = new List<int>(16384);
            var meshOrder = new List<string>();
            var tmp = new Mesh();
            try
            {
                foreach (var skin in skins)
                {
                    tmp.Clear();
                    skin.BakeMesh(tmp);
                    AppendMesh(tmp.vertices, tmp.triangles, skin.localToWorldMatrix, verts, tris);
                    meshOrder.Add("skinned:" + FullPath(skin.transform));
                }
                foreach (var mf in filters)
                {
                    var m = mf.sharedMesh;
                    AppendMesh(m.vertices, m.triangles, mf.transform.localToWorldMatrix, verts, tris);
                    meshOrder.Add("static:" + FullPath(mf.transform));
                }
            }
            finally { DestroyImmediate(tmp); }
            var orderedJoints = joints.OrderBy(j => j.semanticName.Trim(), StringComparer.Ordinal).ToList();
            var jointRf = new Dictionary<string, Vector3>(StringComparer.Ordinal);
            var jointSrc = new Dictionary<string, Vector3>(StringComparer.Ordinal);
            foreach (var j in orderedJoints)
            {
                Vector3 w = j.source.position;
                jointSrc[j.semanticName.Trim()] = w;
                jointRf[j.semanticName.Trim()] = ToRf(w);
            }
            for (int i=0; i<verts.Count; i++) verts[i] = new Vector3(verts[i].x-rfRoot.x,verts[i].y,verts[i].z);
            foreach (var key in jointRf.Keys.ToList()) { var v=jointRf[key]; jointRf[key]=new Vector3(v.x-rfRoot.x,v.y,v.z); }
            string stem = string.Format(CultureInfo.InvariantCulture, "{0}_f{1:0000}", baseName, frame);
            WriteObj(Path.Combine(outDir, stem + ".obj"), frame, timeS, verts, tris);
            WriteSnapshot(Path.Combine(outDir, stem + ".snapshot.json"), timeS, orderedJoints.Select(j => j.semanticName.Trim()).ToList(), jointRf, verts, tris, rfRootOut);
            WriteProvenance(Path.Combine(outDir, stem + ".provenance.json"), frame, timeS, meshOrder, jointSrc, rfRoot, srcRootWorld, rfRoot0, srcRoot0);
        }

        void AppendMesh(Vector3[] srcVerts, int[] srcTris, Matrix4x4 localToWorld, List<Vector3> verts, List<int> tris)
        {
            int baseIndex = verts.Count;
            for (int i = 0; i < srcVerts.Length; i++)
                verts.Add(ToRf(localToWorld.MultiplyPoint3x4(srcVerts[i])));
            bool reflected = (sourceToRf * localToWorld).determinant < 0;
            for (int i = 0; i < srcTris.Length; i += 3)
            {
                tris.Add(baseIndex + srcTris[i]);
                tris.Add(baseIndex + srcTris[i + (reflected ? 2 : 1)]);
                tris.Add(baseIndex + srcTris[i + (reflected ? 1 : 2)]);
            }
        }

        void WriteObj(string path, int frame, double timeS, List<Vector3> verts, List<int> tris)
        {
            var sb = new StringBuilder(verts.Count * 24 + tris.Count * 8 + 256);
            sb.Append("# RunFlow Phase-0 reference capture. Private source, do not redistribute. frame=")
              .Append(frame.ToString(CultureInfo.InvariantCulture)).Append(" time_s=")
              .Append(Fd(timeS)).Append(" unit=m cs=RF_X_FORWARD_Z_UP\n");
            for (int i = 0; i < verts.Count; i++)
                sb.Append("v ").Append(F(verts[i].x)).Append(' ').Append(F(verts[i].y)).Append(' ').Append(F(verts[i].z)).Append('\n');
            for (int i = 0; i + 2 < tris.Count; i += 3)
                sb.Append("f ").Append((tris[i] + 1).ToString(CultureInfo.InvariantCulture)).Append(' ')
                  .Append((tris[i + 1] + 1).ToString(CultureInfo.InvariantCulture)).Append(' ')
                  .Append((tris[i + 2] + 1).ToString(CultureInfo.InvariantCulture)).Append('\n');
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
        }

        void WriteSnapshot(string path, double timeS, List<string> jointOrder, Dictionary<string, Vector3> jointRf, List<Vector3> verts, List<int> tris, Vector3 rfRootOut)
        {
            var sb = new StringBuilder(verts.Count * 24 + 4096);
            sb.Append("{\"schema_version\":\"1\",");
            sb.Append("\"time_s\":").Append(Fd(timeS)).Append(',');
            sb.Append("\"joints\":{");
            for (int i = 0; i < jointOrder.Count; i++)
            {
                if (i > 0) sb.Append(',');
                var v = jointRf[jointOrder[i]];
                sb.Append(JsonStr(jointOrder[i])).Append(":[").Append(F(v.x)).Append(',').Append(F(v.y)).Append(',').Append(F(v.z)).Append(']');
            }
            sb.Append("},\"parts\":[");
            for (int i = 0; i < includedParts.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append(JsonStr(includedParts[i]));
            }
            sb.Append("],\"vertices\":[");
            for (int i = 0; i < verts.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append('[').Append(F(verts[i].x)).Append(',').Append(F(verts[i].y)).Append(',').Append(F(verts[i].z)).Append(']');
            }
            sb.Append("],\"triangles\":[");
            for (int i = 0; i + 2 < tris.Count; i += 3)
            {
                if (i > 0) sb.Append(',');
                sb.Append('[').Append(tris[i].ToString(CultureInfo.InvariantCulture)).Append(',')
                  .Append(tris[i + 1].ToString(CultureInfo.InvariantCulture)).Append(',')
                  .Append(tris[i + 2].ToString(CultureInfo.InvariantCulture)).Append(']');
            }
            sb.Append("],\"root_position\":[").Append(F(rfRootOut.x)).Append(',').Append(F(rfRootOut.y)).Append(',').Append(F(rfRootOut.z)).Append("],");
            sb.Append("\"unit\":\"m\",\"coordinate_system\":\"RF_X_FORWARD_Z_UP\"}");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
        }

        void WriteProvenance(string path, int frame, double timeS, List<string> meshOrder, Dictionary<string, Vector3> jointSrc, Vector3 rfRootOrig, Vector3 srcRootWorld, Vector3 rfRoot0, Vector3 srcRoot0)
        {
            var sb = new StringBuilder(4096);
            sb.Append("{\"runflow_phase\":\"0\",\"capture_tool\":\"integrations/unity/RunFlowCapture.cs\",");
            sb.Append("\"animator\":").Append(JsonStr(animator != null ? animator.name : "")).Append(',');
            sb.Append("\"root\":").Append(JsonStr(root != null ? FullPath(root) : "")).Append(',');
            sb.Append("\"trajectory_root\":").Append(JsonStr(FullPath(trajectoryRoot != null ? trajectoryRoot : root))).Append(',');
            sb.Append("\"clip\":").Append(JsonStr(clip != null ? clip.name : "")).Append(',');
            sb.Append("\"animator_state\":").Append(JsonStr(animatorStateName)).Append(',');
            sb.Append("\"clip_length_s\":").Append(clip != null ? F(clip.length) : "0.000000").Append(',');
            sb.Append("\"frame\":").Append(frame.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"time_s\":").Append(Fd(timeS)).Append(",\"fps\":").Append(F(fps)).Append(',');
            sb.Append("\"source_to_rf\":[");
            for (int r = 0; r < 4; r++)
            {
                if (r > 0) sb.Append(',');
                sb.Append('[');
                for (int c = 0; c < 4; c++) { if (c > 0) sb.Append(','); sb.Append(F(sourceToRf[r, c])); }
                sb.Append(']');
            }
            sb.Append("],\"rf_scale\":").Append(F(rfScale)).Append(',');
            sb.Append("\"source_root_world\":[").Append(F(srcRootWorld.x)).Append(',').Append(F(srcRootWorld.y)).Append(',').Append(F(srcRootWorld.z)).Append("],");
            sb.Append("\"source_root_first\":[").Append(F(srcRoot0.x)).Append(',').Append(F(srcRoot0.y)).Append(',').Append(F(srcRoot0.z)).Append("],");
            sb.Append("\"rf_root_original\":[").Append(F(rfRootOrig.x)).Append(',').Append(F(rfRootOrig.y)).Append(',').Append(F(rfRootOrig.z)).Append("],");
            sb.Append("\"rf_root_first\":[").Append(F(rfRoot0.x)).Append(',').Append(F(rfRoot0.y)).Append(',').Append(F(rfRoot0.z)).Append("],");
            sb.Append("\"root_policy\":\"mesh and joints subtract root X; root_position retains original trajectory; Y/Z preserved\",");
            sb.Append("\"warmup_seconds\":").Append(F(warmupSeconds)).Append(',');
            sb.Append("\"simulation_steps_per_sample\":").Append(simulationStepsPerSample).Append(',');
            sb.Append("\"parts_review_reference\":").Append(JsonStr(partsReviewReference ?? "")).Append(',');
            sb.Append("\"diagnostic_only\":").Append(diagnosticOnly ? "true" : "false").Append(',');
            sb.Append("\"scientific_status\":\"PENDING_HUMAN_REVIEW\",");
            sb.Append("\"mesh_order\":[");
            for (int i = 0; i < meshOrder.Count; i++) { if (i > 0) sb.Append(','); sb.Append(JsonStr(meshOrder[i])); }
            sb.Append("],\"joint_sources\":{");
            bool first = true;
            foreach (var kv in jointSrc.OrderBy(k => k.Key, StringComparer.Ordinal))
            {
                if (!first) sb.Append(',');
                first = false;
                sb.Append(JsonStr(kv.Key)).Append(":[").Append(F(kv.Value.x)).Append(',').Append(F(kv.Value.y)).Append(',').Append(F(kv.Value.z)).Append(']');
            }
            sb.Append("},");
            sb.Append("\"spring\":\"explicit reset and fixed step hooks; verified=").Append(hasVerifiedSpringIntegration ? "true" : "false").Append("\",");
            sb.Append("\"unity_version\":").Append(JsonStr(Application.unityVersion)).Append(',');
            sb.Append("\"captured_utc\":").Append(JsonStr(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture))).Append(',');
            sb.Append("\"ip_note\":\"Pinned user source only. Outputs are private to outputDirectory and must not be redistributed.\"}");
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
        }
    }
}
