param([string]$RunName = ('smoke-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
if ($RunName -notmatch '^[A-Za-z0-9_-]+$') { throw 'RunName must be a filename' }
$output = Join-Path $repoRoot ('private\phase1\' + $RunName)
if (Test-Path -LiteralPath $output) { throw 'Fresh run required; no automatic retry' }
$cli = Join-Path $repoRoot '.venv\Scripts\runflow.exe'
$assetRoot = Join-Path $repoRoot 'private\oguri\adopted-002'
& $cli cfd prepare (Join-Path $assetRoot 'configuration-final-002\manifest.json') `
    --asset-root $assetRoot --protocol (Join-Path $repoRoot 'configs\cfd.phase1-smoke.json') --output $output --frame 0
if (-not (Test-Path -LiteralPath (Join-Path $output 'result.json'))) { throw 'Preflight failed; no trial started' }
$prepared = Get-Content (Join-Path $output 'result.json') -Raw | ConvertFrom-Json
if ($prepared.execution_status -eq 'PREPARED') { & $cli cfd run --output $output }
& $cli cfd report --output $output
$result = Get-Content (Join-Path $output 'result.json') -Raw | ConvertFrom-Json
Write-Output ('Result: ' + $result.execution_status + '; reason: ' + $result.reason)
Write-Output ('Private evidence: ' + $output)
if ($result.execution_status -ne 'PASS') { exit 2 }
