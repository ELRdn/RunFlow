// Explicit diagnostic runner for the pinned UmaViewer source. Never approves a gait.
#if UNITY_EDITOR
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEditor;
using UnityEditor.Events;

namespace RunFlow
{
    public sealed class RunFlowBatchDriver : MonoBehaviour
    {
        public string output;
        public string adoptionInput;
        public int sampleCount = 16;
        JObject adoption;
        public const string Motion = "3d/motion/racemain/body/type01/anm_rac_type01_run02_base";
        UmaContainerCharacter uma;
        static string PathOf(Transform t)
        {
            var names = new Stack<string>();
            for (; t != null; t = t.parent) names.Push(t.name);
            return string.Join("/", names);
        }
        static void Save(string path, object value)
        { File.WriteAllText(path, JsonConvert.SerializeObject(value, Formatting.Indented)); }
        static string HashFile(string path)
        {
            using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))
            using(var sha=System.Security.Cryptography.SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
        }

        IEnumerator Start()
        {
            var deadline = Time.realtimeSinceStartup + 300;
            while (UmaViewerBuilder.Instance == null || UmaViewerBuilder.Instance.ShaderList.Count == 0)
            {
                if (Time.realtimeSinceStartup > deadline) { Fail("UmaViewer initialization timed out"); yield break; }
                yield return null;
            }
            try
            {
                if (!Application.unityVersion.StartsWith("2022.3.62f1")) throw new Exception("Wrong Editor version");
                if (Directory.Exists(output)) throw new Exception("Fresh private output required");
                Directory.CreateDirectory(output);
                if (!string.IsNullOrEmpty(adoptionInput))
                {
                    adoption = JObject.Parse(File.ReadAllText(adoptionInput));
                    if ((string)adoption["decision"]["motion_id"] != Motion ||
                        (string)adoption["decision"]["character_id"] != "1006" ||
                        (string)adoption["decision"]["costume_id"] != "100602" ||
                        (bool?)adoption["decision"]["phase"]["research_reference_accepted"] != true ||
                        (bool?)adoption["decision"]["scale"]["research_scale_accepted"] != true ||
                        (double?)adoption["decision"]["scale"]["meters_per_unity_world_unit"] != 1 ||
                        (double?)adoption["decision"]["scale"]["additional_scale_factor"] != 1 ||
                        (string)adoption["parts_review"]["judgment"] != "ACCEPTED_WITH_NOTED_INTERSECTION")
                        throw new Exception("Adoption does not authorize this target/scale/parts policy");
                    File.Copy(adoptionInput, Path.Combine(output,"adoption-input.json"));
                }
                if (sampleCount != 16 && sampleCount != 32) throw new Exception("Only 16 or 32 phase samples are supported");
                if (sampleCount != 16 && adoption == null) throw new Exception("Dense cycle capture requires adopted phase/scale");
                for (int run = 0; run < 2; run++) Run(run);
                Save(Path.Combine(output, "completed.json"), new { execution_status="CAPTURED", samples_per_run=sampleCount,
                    unity_version=Application.unityVersion, canonical_verified=false,
                    scientific_status="PENDING_HUMAN_REVIEW", diagnostic_only=adoption==null,
                    research_conditions_adopted=adoption!=null });
                EditorApplication.Exit(0);
            }
            catch (Exception e) { Fail(e.ToString()); }
        }

        void Fail(string message)
        {
            Directory.CreateDirectory(output);
            Save(Path.Combine(output,"failure.json"),new { execution_status="FAIL", message });
            Debug.LogError("RunFlow capture failed: " + message);
            EditorApplication.Exit(2);
        }

        void Run(int index)
        {
            var builder = UmaViewerBuilder.Instance;
            UmaViewerUI.Instance.ModelSettings.IsHeadFix=false;
            UmaViewerUI.Instance.ModelSettings.IsTPose=false;
            if (builder.CurrentUMAContainer != null) DestroyImmediate(builder.CurrentUMAContainer.gameObject);
            // 02 is the model suffix for dress 100602, not card 100603.
            var load = builder.LoadUma(new CharaEntry { Id=1006, Name="オグリキャップ" }, "02", false);
            while (load.MoveNext()) if (load.Current != null) throw new Exception("Unexpected asynchronous model loader");
            uma = builder.CurrentUMAContainer;
            if (uma == null || uma.Body == null || uma.Head == null || uma.Tail == null)
                throw new Exception("Required body/head/tail missing");
            uma.EnableEyeTracking = false;
            var entry = UmaViewerMain.Instance.AbList[Motion];
            uma.LoadAnimation(entry);
            var clip = uma.OverrideController["clip_2"];
            if (clip == null || clip.name != Motion || clip.length <= 0) throw new Exception("Wrong clip");
            if (!clip.isLooping) throw new Exception("Candidate is not a loop; explicit cycle handling required");
            var animator = uma.UmaAnimator;
            animator.cullingMode=AnimatorCullingMode.AlwaysAnimate;
            animator.applyRootMotion=true;
            animator.speed=1;
            uma.transform.position=Vector3.zero;
            uma.transform.rotation=Quaternion.identity;
            if (uma.UmaFaceAnimator != null)
            {
                uma.UmaFaceAnimator.cullingMode=AnimatorCullingMode.AlwaysAnimate;
                uma.UmaFaceAnimator.speed=1;
                uma.UmaFaceAnimator.Rebind();
                uma.UmaFaceAnimator.Update(0);
            }
            if(uma.Position==null) throw new Exception("Source Position root missing");
            var transforms=uma.Position.GetComponentsInChildren<Transform>(true);
            Save(Path.Combine(output,"transforms-"+index+".json"),transforms.Select(t=>new { t.name,path=PathOf(t), position=new[]{t.position.x,t.position.y,t.position.z} }));
            var bridge=uma.gameObject.AddComponent<RunFlowSpringBridge>();
            bridge.springs=uma.GetComponentsInChildren<DynamicBone>(true)
                .Where(s=>s.enabled && s.gameObject.activeInHierarchy).OrderBy(s=>PathOf(s.transform),StringComparer.Ordinal).ToArray();
            foreach(var s in bridge.springs) s.m_DistantDisable=false;
            // Exercise the actual patched methods before allowing capture, without asserting reproducibility.
            bridge.Begin(); bridge.BeforeAnimation(); animator.Update(0); AfterAnimation(0); bridge.Step(clip.length/64); bridge.End();
            var capture=uma.gameObject.AddComponent<RunFlowCapture>();
            capture.frameCount=sampleCount;
            capture.animator=animator; capture.root=uma.transform; capture.clip=clip; capture.animatorStateName="motion_2";
            capture.trajectoryRoot=uma.Position;
            capture.fps=64/clip.length; capture.simulationStepsPerSample=4; capture.warmupSeconds=5*clip.length;
            capture.allowLoopBeyondClipLength=true; capture.diagnosticOnly=true;
            capture.partsReviewReference="";
            if (adoption != null)
            {
                capture.fps=256/clip.length; capture.simulationStepsPerSample=256/sampleCount;
                capture.startPhaseSeconds=(double)adoption["decision"]["phase"]["phase_s"];
                capture.diagnosticOnly=false;
                capture.partsReviewReference="prior multiview review with costume-leg exception; sha256="+(string)adoption["parts_review_sha256"];
                if (Math.Abs(uma.BodyScale-(double)adoption["decision"]["scale"]["existing_body_scale"]) > 1e-7)
                    throw new Exception("Original BodyScale differs from adopted source");
            }
            // Nominal Unity units only. No fit to nominal height, no scientific scale approval.
            capture.sourceToRf=Matrix4x4.zero;
            capture.sourceToRf[0,2]=1; capture.sourceToRf[1,0]=1; capture.sourceToRf[2,1]=1; capture.sourceToRf[3,3]=1;
            capture.sourceToRfConfigured=true; capture.rfScale=1;
            capture.includedParts=new List<string>{"head","torso","left_arm","right_arm","left_leg","right_leg","ears","hair","tail","costume"};
            var bindings=new Dictionary<string,string>{{"head","Head"},{"hip","Hip"},{"left_hand","Wrist_L"},
                {"right_hand","Wrist_R"},{"left_knee","Knee_L"},{"right_knee","Knee_R"},{"left_foot","Ankle_L"},{"right_foot","Ankle_R"}};
            foreach(var pair in bindings)
            {
                if(pair.Key=="head" && uma.HeadBone!=null)
                {
                    capture.joints.Add(new RunFlowCapture.JointBinding{semanticName=pair.Key,source=uma.HeadBone.transform});
                    continue;
                }
                var matches=transforms.Where(t=>t.name==pair.Value).ToArray();
                if(matches.Length!=1) throw new Exception("Ambiguous/missing bone: "+pair.Value);
                capture.joints.Add(new RunFlowCapture.JointBinding{semanticName=pair.Key,source=matches[0]});
            }
            UnityEventTools.AddPersistentListener(capture.onResetUmaViewerSprings,bridge.Begin);
            UnityEventTools.AddPersistentListener(capture.onBeforeAnimation,bridge.BeforeAnimation);
            UnityEventTools.AddPersistentListener(capture.onAfterAnimation,AfterAnimation);
            UnityEventTools.AddPersistentListener(capture.onStepUmaViewerSprings,bridge.Step);
            UnityEventTools.AddPersistentListener(capture.onFinish,bridge.End);
            capture.hasVerifiedSpringIntegration=true; // Concrete manual API calls above succeeded; equality is checked separately.
            capture.outputDirectory=Path.Combine(output,index==0?"unity-a":"unity-b");
            var inputs=UmaViewerMain.Instance.AbList.Values.Where(e=>UmaAssetManager.Exist(e))
                .OrderBy(e=>e.Name,StringComparer.Ordinal).ToArray();
            var hashes=inputs.Select(e=>HashFile(e.Path)).ToArray();
            if (adoption != null)
            {
                var assetDir=Path.Combine(output,"source-assets"); Directory.CreateDirectory(assetDir);
                for(int n=0;n<inputs.Length;n++)
                {
                    var dest=Path.Combine(assetDir,hashes[n]);
                    if(!File.Exists(dest)) File.Copy(inputs[n].Path,dest);
                    if(HashFile(dest)!=hashes[n]) throw new Exception("Archived asset hash mismatch");
                }
            }
            var metaPath=System.IO.Path.Combine(Config.Instance.MainPath,"meta");
            var masterPath=System.IO.Path.Combine(Config.Instance.MainPath,"master/master.mdb");
            var metaHash=HashFile(metaPath); var masterHash=HashFile(masterPath);
            Save(Path.Combine(output,"inputs-"+index+".json"), new { meta_sha256=metaHash,master_sha256=masterHash,
                assets=inputs.Select((e,n)=>new {source_path=e.Name,locator=e.Url,sha256=hashes[n]}),
                capture_scripts=Directory.GetFiles(System.IO.Path.Combine(Application.dataPath,"RunFlow"),"*.cs")
                    .OrderBy(f=>f,StringComparer.Ordinal).Select(f=>new {name=System.IO.Path.GetFileName(f),sha256=HashFile(f)}) });
            Save(Path.Combine(output,"inventory-"+index+".json"), new {
                character_id="1006", costume_id="100602", model_suffix="02", motion=Motion,
                clip_length_s=clip.length, clip_loop=clip.isLooping, scale_status=adoption==null?"NOMINAL_UNITY_UNIT_UNREVIEWED":"USER_ADOPTED_ORIGINAL_SCALE_NOT_CALIBRATED",
                source_forward="+Z assumed from model convention; pending review", scientific_status="PENDING_HUMAN_REVIEW",
                phase_origin=adoption==null?"clip start after five loops; contact event unverified":"user-adopted right shoe crossing; phase reset then five warmup loops", spring_order=bridge.springs.Select(s=>PathOf(s.transform)),
                renderers=uma.GetComponentsInChildren<SkinnedMeshRenderer>(true).Select(s=>new {path=PathOf(s.transform),s.enabled,
                    active=s.gameObject.activeInHierarchy,vertices=s.sharedMesh==null?0:s.sharedMesh.vertexCount}),
                joints=capture.joints.Select(j=>new {j.semanticName,path=PathOf(j.source)}),
                behaviours=uma.GetComponentsInChildren<MonoBehaviour>(true).Where(b=>b!=null).Select(b=>b.GetType().FullName).Distinct().OrderBy(n=>n),
                missing_behaviour_count=uma.GetComponentsInChildren<MonoBehaviour>(true).Count(b=>b==null),
                face_control=uma.isAnimatorControl, body_scale=uma.BodyScale });
            capture.CaptureSequence();
            for(int n=0;n<inputs.Length;n++) if(HashFile(inputs[n].Path)!=hashes[n]) throw new Exception("Input changed during capture");
            if(HashFile(metaPath)!=metaHash || HashFile(masterPath)!=masterHash) throw new Exception("Game metadata changed during capture");
        }
        public void AfterAnimation(float dt)
        {
            if(uma.UmaFaceAnimator!=null) uma.UmaFaceAnimator.Update(dt);
            if(uma.isAnimatorControl && uma.FaceDrivenKeyTarget!=null) uma.FaceDrivenKeyTarget.ProcessLocator();
        }
    }
    public static class RunFlowBatchEntry
    {
        public static void Execute()
        {
            var args=Environment.GetCommandLineArgs();
            var i=Array.IndexOf(args,"-runFlowOutput");
            if(i<0 || i+1>=args.Length) throw new Exception("-runFlowOutput required");
            var output=Path.GetFullPath(args[i+1]);
            UnityEditor.SceneManagement.EditorSceneManager.OpenScene("Assets/Scenes/Version2.unity");
            var go=new GameObject("RunFlowDiagnostic");
            var driver=go.AddComponent<RunFlowBatchDriver>(); driver.output=output;
            var adoptionIndex=Array.IndexOf(args,"-runFlowAdoption");
            if(adoptionIndex>=0) driver.adoptionInput=Path.GetFullPath(args[adoptionIndex+1]);
            var sampleIndex=Array.IndexOf(args,"-runFlowSamples");
            if(sampleIndex>=0) driver.sampleCount=int.Parse(args[sampleIndex+1]);
            EditorApplication.isPlaying=true;
        }
    }
}
#endif
