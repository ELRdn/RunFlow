// Private neutral-pose/foot-motion measurements. No approval or source deformation.
#if UNITY_EDITOR
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using UnityEditor;
using UnityEngine;

namespace RunFlow
{
    public sealed class RunFlowMeasurementDriver : MonoBehaviour
    {
        public string output;
        UmaContainerCharacter uma;
        static float[] Rf(Vector3 v) { return new[]{v.z,v.x,v.y}; }
        static string BonePath(Transform t)
        {
            var path=new Stack<string>();
            for(;t!=null;t=t.parent) path.Push(t.name);
            return string.Join("/",path);
        }
        static string Hash(string path)
        {
            using(var f=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))
            using(var sha=System.Security.Cryptography.SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(f)).Replace("-","").ToLowerInvariant();
        }
        static void Save(string path,object value)
        { File.WriteAllText(path,JsonConvert.SerializeObject(value)); }
        static object Inputs()
        {
            return new {
                meta_sha256=Hash(Path.Combine(Config.Instance.MainPath,"meta")),
                master_sha256=Hash(Path.Combine(Config.Instance.MainPath,"master/master.mdb")),
                assets=UmaViewerMain.Instance.AbList.Values.Where(e=>UmaAssetManager.Exist(e))
                    .OrderBy(e=>e.Name,StringComparer.Ordinal).Select(e=>new{source_path=e.Name,sha256=Hash(e.Path)}).ToArray(),
                scripts=Directory.GetFiles(Path.Combine(Application.dataPath,"RunFlow"),"*.cs").OrderBy(f=>f,StringComparer.Ordinal)
                    .Select(f=>new{name=Path.GetFileName(f),sha256=Hash(f)}).ToArray(),
                dynamic_bone_sha256=Hash(Path.Combine(Application.dataPath,"Scripts/DynamicBone/Scripts/DynamicBone.cs"))
            };
        }
        IEnumerator Start()
        {
            float deadline=Time.realtimeSinceStartup+300;
            while(UmaViewerBuilder.Instance==null || UmaViewerBuilder.Instance.ShaderList.Count==0)
            {
                if(Time.realtimeSinceStartup>deadline) { Fail("Initialization timeout"); yield break; }
                yield return null;
            }
            try
            {
                if(Application.unityVersion!="2022.3.62f1") throw new Exception("Wrong Unity version");
                if(Directory.Exists(output)) throw new Exception("Fresh output required");
                Directory.CreateDirectory(output);
                // Equalize loaded input bundles before both fresh-model measurements.
                Load(false);
                uma.LoadAnimation(UmaViewerMain.Instance.AbList[RunFlowBatchDriver.Motion]);
                for(int run=0;run<2;run++) Measure(run);
                Save(Path.Combine(output,"completed.json"),new{execution_status="MEASURED",unity_version=Application.unityVersion,
                    samples_per_cycle=256,cycles=2,runs=2,scientific_status="PENDING_HUMAN_REVIEW"});
                EditorApplication.Exit(0);
            }
            catch(Exception e) { Fail(e.ToString()); }
        }
        void Fail(string error)
        {
            Directory.CreateDirectory(output);
            Save(Path.Combine(output,"failure.json"),new{execution_status="FAIL",error});
            Debug.LogError(error); EditorApplication.Exit(2);
        }
        void Load(bool neutral)
        {
            var b=UmaViewerBuilder.Instance;
            if(b.CurrentUMAContainer!=null) DestroyImmediate(b.CurrentUMAContainer.gameObject);
            UmaViewerUI.Instance.ModelSettings.IsHeadFix=false;
            UmaViewerUI.Instance.ModelSettings.IsTPose=neutral;
            var loader=b.LoadUma(new CharaEntry{Id=1006,Name="オグリキャップ"},"02",false);
            while(loader.MoveNext()) if(loader.Current!=null) throw new Exception("Unexpected asynchronous load");
            uma=b.CurrentUMAContainer;
            if(uma==null || uma.Position==null || uma.HeadBone==null) throw new Exception("Missing character");
            uma.transform.position=Vector3.zero; uma.transform.rotation=Quaternion.identity;
            uma.EnableEyeTracking=false;
            uma.UmaAnimator.cullingMode=AnimatorCullingMode.AlwaysAnimate;
        }
        Transform Bone(string name)
        {
            return uma.Position.GetComponentsInChildren<Transform>(true).Single(t=>t.name==name);
        }
        static float[][] Bake(SkinnedMeshRenderer skin)
        {
            var tmp=new Mesh();
            try
            {
                skin.BakeMesh(tmp);
                return tmp.vertices.Select(v=>Rf(skin.localToWorldMatrix.MultiplyPoint3x4(v))).ToArray();
            }
            finally { DestroyImmediate(tmp); }
        }
        static int[][] Triangles(Mesh mesh)
        {
            var raw=mesh.triangles;
            return Enumerable.Range(0,raw.Length/3).Select(n=>new[]{raw[n*3],raw[n*3+1],raw[n*3+2]}).ToArray();
        }
        static float[] EarWeights(SkinnedMeshRenderer skin)
        {
            var ear=skin.bones.Select(b=>b!=null && BonePath(b).Contains("/Sp_He_Ear0_")).ToArray();
            return skin.sharedMesh.boneWeights.Select(w=>
                (ear[w.boneIndex0]?w.weight0:0)+(ear[w.boneIndex1]?w.weight1:0)+
                (ear[w.boneIndex2]?w.weight2:0)+(ear[w.boneIndex3]?w.weight3:0)).ToArray();
        }
        static int[] FootIndices(SkinnedMeshRenderer body,Transform ankle)
        {
            var indices=new List<int>(); var weights=body.sharedMesh.boneWeights;
            for(int i=0;i<weights.Length;i++)
            {
                var w=weights[i]; float sum=0;
                var ids=new[]{w.boneIndex0,w.boneIndex1,w.boneIndex2,w.boneIndex3};
                var ws=new[]{w.weight0,w.weight1,w.weight2,w.weight3};
                for(int j=0;j<4;j++) if(ws[j]>0 && body.bones[ids[j]]!=null &&
                    (body.bones[ids[j]]==ankle || body.bones[ids[j]].IsChildOf(ankle))) sum+=ws[j];
                if(sum>=.8f) indices.Add(i);
            }
            if(indices.Count<10) throw new Exception("Foot vertex selection failed");
            return indices.ToArray();
        }
        void Face(float dt)
        {
            if(uma.UmaFaceAnimator!=null) uma.UmaFaceAnimator.Update(dt);
            if(uma.isAnimatorControl && uma.FaceDrivenKeyTarget!=null) uma.FaceDrivenKeyTarget.ProcessLocator();
        }
        void Measure(int index)
        {
            Load(true);
            var neutralInputs=Inputs();
            var body=uma.GetComponentsInChildren<SkinnedMeshRenderer>(true).Single(s=>s.name=="M_Body");
            var left=FootIndices(body,Bone("Ankle_L")); var right=FootIndices(body,Bone("Ankle_R"));
            var skins=uma.GetComponentsInChildren<SkinnedMeshRenderer>(true)
                .Where(s=>s.enabled && s.gameObject.activeInHierarchy).OrderBy(s=>BonePath(s.transform),StringComparer.Ordinal).ToArray();
            Save(Path.Combine(output,"neutral-"+index+".json"),new{
                character_id="1006",costume_id="100602",pose="IsTPose=true suppresses idle clip and smile; merged prefab bind pose; no Animator.Update",
                db_scale=Convert.ToInt32(uma.CharaData["scale"]),body_scale=uma.BodyScale,
                position_local_scale=Rf(uma.Position.localScale),unit="nominal_unity_world_unit",coordinate_system="RF_X_FORWARD_Z_UP",
                feet=new{left_vertex_indices=left,right_vertex_indices=right,selection="M_Body ankle-or-descendant skin weight sum >= 0.8"},
                meshes=skins.Select(s=>new{name=s.name,path=BonePath(s.transform),vertices=Bake(s),
                    triangles=Triangles(s.sharedMesh),ear_skin_weights=EarWeights(s)}),
                bones=uma.Position.GetComponentsInChildren<Transform>(true).Select(t=>new{name=t.name,path=BonePath(t),position=Rf(t.position)}).ToArray()
            });
            if(JsonConvert.SerializeObject(neutralInputs)!=JsonConvert.SerializeObject(Inputs())) throw new Exception("Neutral inputs changed");
            Save(Path.Combine(output,"neutral-inputs-"+index+".json"),neutralInputs);

            Load(false);
            uma.LoadAnimation(UmaViewerMain.Instance.AbList[RunFlowBatchDriver.Motion]);
            var clip=uma.OverrideController["clip_2"];
            if(clip==null || clip.name!=RunFlowBatchDriver.Motion || !clip.isLooping) throw new Exception("Wrong loop");
            var inputs=Inputs();
            Save(Path.Combine(output,"motion-inputs-"+index+".json"),inputs);
            body=uma.GetComponentsInChildren<SkinnedMeshRenderer>(true).Single(s=>s.name=="M_Body");
            var l=Bone("Ankle_L");var r=Bone("Ankle_R");
            if(!left.SequenceEqual(FootIndices(body,l)) || !right.SequenceEqual(FootIndices(body,r))) throw new Exception("Foot topology changed");
            var bridge=uma.gameObject.AddComponent<RunFlowSpringBridge>();
            bridge.springs=uma.GetComponentsInChildren<DynamicBone>(true).Where(s=>s.enabled && s.gameObject.activeInHierarchy)
                .OrderBy(s=>BonePath(s.transform),StringComparer.Ordinal).ToArray();
            foreach(var spring in bridge.springs) spring.m_DistantDisable=false;
            var animator=uma.UmaAnimator;
            animator.applyRootMotion=true;animator.speed=1;animator.Rebind();animator.Play("motion_2",0,0);animator.Update(0);
            if(!animator.GetCurrentAnimatorClipInfo(0).Any(c=>c.clip==clip)) throw new Exception("Wrong active clip");
            if(uma.UmaFaceAnimator!=null) { uma.UmaFaceAnimator.Rebind();uma.UmaFaceAnimator.Update(0); }
            float dt=clip.length/256;
            var samples=new List<object>();
            bridge.Begin();
            try
            {
                Face(0);
                for(int step=0;step<=7*256;step++)
                {
                    if(step>0) { bridge.BeforeAnimation();animator.Update(dt);Face(dt);bridge.Step(dt); }
                    if(step<5*256) continue;
                    var vertices=Bake(body);
                    samples.Add(new{index=step-5*256,time_s=step*(double)dt,phase_s=(step-5*256)*(double)dt,
                        animator_normalized_time=animator.GetCurrentAnimatorStateInfo(0).normalizedTime,
                        root=Rf(uma.Position.position),hip=Rf(Bone("Hip").position),
                        left_ankle=Rf(l.position),right_ankle=Rf(r.position),
                        left_vertices=left.Select(i=>vertices[i]).ToArray(),right_vertices=right.Select(i=>vertices[i]).ToArray()});
                }
            }
            finally { bridge.End(); }
            Save(Path.Combine(output,"feet-"+index+".json"),new{clip=clip.name,clip_length_s=clip.length,
                step_s=dt,warmup_steps=1280,samples_per_cycle=256,cycles=2,endpoint_included=true,
                unit="nominal_unity_world_unit",coordinate_system="RF_X_FORWARD_Z_UP",ground_plane_verified=false,
                left_vertex_indices=left,right_vertex_indices=right,samples});
            if(JsonConvert.SerializeObject(inputs)!=JsonConvert.SerializeObject(Inputs())) throw new Exception("Motion inputs changed");
        }
    }
    public static class RunFlowMeasurementEntry
    {
        public static void Execute()
        {
            var args=Environment.GetCommandLineArgs();int i=Array.IndexOf(args,"-runFlowOutput");
            if(i<0 || i+1>=args.Length) throw new Exception("Private output required");
            string output=Path.GetFullPath(args[i+1]);
            if(output.IndexOf(Path.DirectorySeparatorChar+"private"+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)<0)
                throw new Exception("Output must be private");
            UnityEditor.SceneManagement.EditorSceneManager.OpenScene("Assets/Scenes/Version2.unity");
            new GameObject("RunFlowMeasurements").AddComponent<RunFlowMeasurementDriver>().output=output;
            EditorApplication.isPlaying=true;
        }
    }
}
#endif
