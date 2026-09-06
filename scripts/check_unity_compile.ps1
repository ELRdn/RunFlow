param([string]$EditorRoot = 'C:\Program Files\Unity 2022.3.62f1\Editor')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$runtimeDlls = Join-Path $repoRoot '.tools\umaviewer\runtime\build\StandaloneWindows64\UmaViewer_Data\Managed'
$compileArgs = @('/nologo','/define:UNITY_EDITOR','/target:library',('/out:' + (Join-Path $repoRoot '.cache\csharp\RunFlowBatchCapture.dll')))
foreach ($dll in @('UnityEngine.CoreModule.dll','UnityEngine.AnimationModule.dll','RootMotionsScript.dll','umamusume.dll','Plugins.dll','netstandard.dll','Newtonsoft.Json.dll')) {
    $compileArgs += '/reference:' + (Join-Path $runtimeDlls $dll)
}
$compileArgs += '/reference:' + (Join-Path $EditorRoot 'Data\Managed\UnityEngine\UnityEditor.CoreModule.dll')
$compileArgs += Join-Path $repoRoot 'private\unity-patch\001\DynamicBone.cs'
foreach ($name in @('RunFlowSpringBridge.cs','RunFlowCapture.cs','RunFlowBatchDriver.cs')) {
    $compileArgs += Join-Path $repoRoot ('integrations\unity\' + $name)
}
& 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' @compileArgs
exit $LASTEXITCODE
