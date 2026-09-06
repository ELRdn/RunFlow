param(
    [string]$Editor = 'C:\Program Files\Unity 2022.3.62f1\Editor\Unity.exe',
    [string]$RunName = ('direct-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
if ($RunName -notmatch '^[A-Za-z0-9_-]+$') { throw 'RunName must be a filename' }
if ((Get-Item -LiteralPath $Editor).VersionInfo.ProductVersion -ne '2022.3.62f1_4af31df58517') { throw 'Wrong Editor version' }
$project = Join-Path $repoRoot '.tools\umaviewer-project\UmaViewer-d50b28379337b507751a7df705a10afeab2c37ce'
$captureOutput = Join-Path $repoRoot ('private\oguri\' + $RunName)
$captureLog = Join-Path $repoRoot ('.cache\unity-' + $RunName + '.log')
if ((Test-Path -LiteralPath $captureOutput) -or (Test-Path -LiteralPath $captureLog)) { throw 'Fresh run name required' }
foreach ($path in @($project,$captureOutput,$captureLog)) { if ($path.Contains('"')) { throw 'Invalid quote in path' } }
# Freeze the reviewed integration sources and their hashes before Unity reads the project.
$patchFile = Join-Path $project 'runflow-patch.json'
$patch = Get-Content -LiteralPath $patchFile -Raw | ConvertFrom-Json
$scriptHashes = @{}
foreach ($file in Get-ChildItem (Join-Path $repoRoot 'integrations\unity') -Filter '*.cs') {
    Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $project ('Assets\RunFlow\' + $file.Name))
    $scriptHashes[$file.Name] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$patch.scripts = $scriptHashes
$patch | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $patchFile -Encoding utf8
$launchArgs = @('-batchmode','-projectPath',('"'+$project+'"'),'-executeMethod','RunFlow.RunFlowBatchEntry.Execute',
    '-runFlowOutput',('"'+$captureOutput+'"'),'-logFile',('"'+$captureLog+'"'))
$unityProcess = Start-Process -FilePath $Editor -ArgumentList $launchArgs -PassThru -WindowStyle Hidden
Write-Output ('Unity PID: ' + $unityProcess.Id + '; log: ' + $captureLog)
if (-not $unityProcess.WaitForExit(1200000)) { throw 'Unity exceeded 20 minutes; inspect its log. No success claimed; process left running.' }
$unityProcess.Refresh()
if ($unityProcess.ExitCode -ne 0 -or -not (Test-Path (Join-Path $captureOutput 'completed.json'))) {
    throw ('Capture did not complete. Inspect ' + $captureLog)
}
& (Join-Path $repoRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'compare_direct_capture.py') `
    --capture-root $captureOutput --blender (Join-Path $repoRoot '.tools\blender\blender-4.2.23-windows-x64\blender.exe')
if ($LASTEXITCODE -ne 0) { throw ('Comparison failed; inspect ' + $captureOutput) }
Write-Output ('Diagnostic comparison complete: ' + (Join-Path $captureOutput 'comparison.json'))
