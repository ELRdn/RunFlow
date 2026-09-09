[CmdletBinding()]
param(
    [string]$ReviewSource = (Join-Path $PSScriptRoot '../private/phase1-validation/repair-final-review-002'),
    [string]$Destination = 'E:\RunFlowPrivate\phase1-validation\fullbody-repair-003\final-review'
)
$ErrorActionPreference = 'Stop'
$reviewSourcePath = (Resolve-Path -LiteralPath $ReviewSource).ProviderPath
$reviewTargetPath = [IO.Path]::GetFullPath($Destination)
$privateRoot = [IO.Path]::GetFullPath('E:\RunFlowPrivate')
if (-not $reviewTargetPath.StartsWith($privateRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Delivery requires a private E: destination.'
}
if (Test-Path -LiteralPath $reviewTargetPath) { throw 'Existing delivery must be preserved.' }
$proof = Get-Content -Raw -LiteralPath (Join-Path $reviewSourcePath 'final-verification.json') | ConvertFrom-Json
if (-not $proof.inputs_unchanged -or -not $proof.summary_stable -or $proof.recorded_owned_processes_alive.Count -ne 0) {
    throw 'The review verification is not complete.'
}
$files = @(Get-ChildItem -LiteralPath $reviewSourcePath -Recurse -File)
foreach ($file in $files) {
    $relative = [IO.Path]::GetRelativePath($reviewSourcePath, $file.FullName).Replace('\', '/')
    $allowed = $relative -in @('final-REVIEW.md','final-summary.json','final-verification.json','final-artifact-sha256.json') -or
        $relative -match '^final-figures/(1000|900)-(whole-body|details|visible-errors|sections)\.png$' -or
        $relative -match '^final-validation/tool-sources/(scripts/(finalize_surface_repair|check_repair_intersections|cfd_worker)\.py|src/runflow/shape_repair\.py)$'
    if (-not $allowed -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw ('Unexpected review file: ' + $relative)
    }
}
Copy-Item -LiteralPath $reviewSourcePath -Destination $reviewTargetPath -Recurse
$receipts = foreach ($file in $files) {
    $relative = [IO.Path]::GetRelativePath($reviewSourcePath, $file.FullName)
    $sourceHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    $targetHash = (Get-FileHash -LiteralPath (Join-Path $reviewTargetPath $relative) -Algorithm SHA256).Hash
    if ($sourceHash -ne $targetHash) { throw ('Delivery hash mismatch: ' + $relative) }
    [pscustomobject]@{path=$relative; sha256=$targetHash.ToLowerInvariant(); bytes=$file.Length}
}
[pscustomobject]@{verified=$true; files=@($receipts); source=$reviewSourcePath; destination=$reviewTargetPath; geometry_changed=$false} |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $reviewTargetPath 'final-delivery-receipt.json') -Encoding utf8
Write-Output ('FINAL_REVIEW_COPIED_AND_VERIFIED: ' + $files.Count)
