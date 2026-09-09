param(
    [string]$Source = 'D:\VibeCoding\RunFlow\private\phase1-validation\local-repair-001',
    [string]$Destination = 'E:\RunFlowPrivate\phase1-validation\local-repair-001'
)
$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath($Source)
$targetRoot = [IO.Path]::GetFullPath($Destination)
$allowedSource = [IO.Path]::GetFullPath('D:\VibeCoding\RunFlow\private\phase1-validation') + '\'
$allowedTarget = [IO.Path]::GetFullPath('E:\RunFlowPrivate\phase1-validation') + '\'
if (-not $sourceRoot.StartsWith($allowedSource,[StringComparison]::OrdinalIgnoreCase) -or
    -not $targetRoot.StartsWith($allowedTarget,[StringComparison]::OrdinalIgnoreCase)) { throw 'Dedicated private source and E destination required' }
if (Test-Path -LiteralPath $targetRoot) { throw 'Destination exists; overwrite refused' }
$state = Get-Content -LiteralPath (Join-Path $sourceRoot 'execution.json') -Raw | ConvertFrom-Json
if (-not $state.finished -or (Test-Path -LiteralPath (Join-Path $sourceRoot 'active-stage.lock'))) { throw 'Study is not frozen' }
$ledgerPath = Join-Path $sourceRoot 'artifact-sha256.json'
$ledger = Get-Content -LiteralPath $ledgerPath -Raw | ConvertFrom-Json
$guardPath = $sourceRoot + '-finalization-guard.json'
$guard = Get-Content -LiteralPath $guardPath -Raw | ConvertFrom-Json
if (-not $guard.complete -or -not $guard.termination_verified -or
    $guard.artifact_ledger_sha256 -ne (Get-FileHash -LiteralPath $ledgerPath).Hash.ToLowerInvariant()) { throw 'Finalization guard did not verify this ledger' }
$drive = [IO.DriveInfo]::new('E:\')
if ($drive.AvailableFreeSpace -lt ([long]$ledger.total_bytes + 50GB)) { throw 'E free-space reserve would be violated' }
$validated = @()
foreach ($property in $ledger.files.PSObject.Properties) {
    $relative = $property.Name.Replace('/','\')
    $from = [IO.Path]::GetFullPath((Join-Path $sourceRoot $relative))
    $to = [IO.Path]::GetFullPath((Join-Path $targetRoot $relative))
    if (-not $from.StartsWith($sourceRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or
        -not $to.StartsWith($targetRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe artifact path' }
    $validated += [pscustomobject]@{ From=$from; To=$to; Sha=$property.Value.sha256; Bytes=[long]$property.Value.bytes }
}
New-Item -ItemType Directory -Path $targetRoot | Out-Null
$count = 0
foreach ($entry in $validated) {
    if ((Get-Item -LiteralPath $entry.From).Length -ne $entry.Bytes -or
        (Get-FileHash -LiteralPath $entry.From -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Sha) { throw ('Source changed: '+$entry.From) }
    $parent = Split-Path -Parent $entry.To
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Copy-Item -LiteralPath $entry.From -Destination $entry.To
    if ((Get-Item -LiteralPath $entry.To).Length -ne $entry.Bytes -or
        (Get-FileHash -LiteralPath $entry.To -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Sha) { throw ('Copied artifact mismatch: '+$entry.To) }
    $count++
    if ($count % 100 -eq 0) { Write-Output ('VERIFIED_ARTIFACTS: '+$count) }
}
Copy-Item -LiteralPath $ledgerPath -Destination (Join-Path $targetRoot 'artifact-sha256.json')
if ((Get-FileHash -LiteralPath $ledgerPath).Hash -ne (Get-FileHash -LiteralPath (Join-Path $targetRoot 'artifact-sha256.json')).Hash) { throw 'Ledger copy mismatch' }
$proof = @{ verified_files=$count; verified_bytes=$ledger.total_bytes; source=$sourceRoot; destination=$targetRoot; scientific_status='UNAPPROVED'; ranking_eligible=$false }
Copy-Item -LiteralPath $guardPath -Destination (Join-Path $targetRoot 'finalization-guard.json')
if ((Get-FileHash -LiteralPath $guardPath).Hash -ne (Get-FileHash -LiteralPath (Join-Path $targetRoot 'finalization-guard.json')).Hash) { throw 'Finalization receipt copy mismatch' }
$proof | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $targetRoot 'E-copy-verification.json') -Encoding utf8
Write-Output ('LOCAL_REPAIR_COPIED_AND_VERIFIED: '+$count)
