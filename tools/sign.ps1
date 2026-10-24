# Signs Windows files with a code-signing certificate (a .pfx file), so Windows SmartScreen shows
# your business name instead of "Unknown publisher".
#
#   powershell -ExecutionPolicy Bypass -File tools\sign.ps1 file1.exe [file2.exe ...]
#
# The certificate comes from two environment variables:
#   IRS_SIGN_PFX           path to the .pfx file
#   IRS_SIGN_PASSWORD      its password
# If IRS_SIGN_PFX is not set, nothing is signed and the build carries on (exit code 0).
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)

$ErrorActionPreference = "Stop"
if (-not $env:IRS_SIGN_PFX) {
    Write-Host "No certificate (IRS_SIGN_PFX not set): files are not signed."
    exit 0
}
if (-not (Test-Path $env:IRS_SIGN_PFX)) { throw "Certificate not found: $env:IRS_SIGN_PFX" }

# signtool.exe comes with the Windows SDK (installed on GitHub's Windows machines)
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $signtool) { throw "signtool.exe not found - install the Windows 10/11 SDK (Signing Tools)." }

$timestamp = if ($env:IRS_SIGN_TIMESTAMP) { $env:IRS_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
foreach ($f in $Files) {
    Write-Host "Signing $f"
    & $signtool.FullName sign /f $env:IRS_SIGN_PFX /p $env:IRS_SIGN_PASSWORD /fd sha256 /tr $timestamp /td sha256 /d "Image Resize & Share" $f
    if ($LASTEXITCODE -ne 0) { throw "Signing failed for $f" }
}
