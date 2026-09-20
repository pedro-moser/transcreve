param(
    [string]$Destination = "packaging/vendor"
)

$ErrorActionPreference = "Stop"
$version = "4.0.0"
$archiveUrl = "https://breakfastquay.com/files/releases/rubberband-$version-gpl-executable-windows.zip"
$sourceUrl = "https://breakfastquay.com/files/releases/rubberband-$version.tar.bz2"
$archiveSha256 = "f2d47fc64dbb42f6cc62edf7933ac4fa89d8f0ef8b9cf97b6afc263a7fe05644"
$sourceSha256 = "af050313ee63bc18b35b2e064e5dce05b276aaf6d1aa2b8a82ced1fe2f8028e9"
$archive = Join-Path $env:RUNNER_TEMP "rubberband-windows.zip"
$extract = Join-Path $env:RUNNER_TEMP "rubberband-windows"
$binDir = Join-Path $Destination "bin"
$licenseDir = Join-Path $Destination "licenses"

New-Item -ItemType Directory -Force -Path $binDir, $licenseDir | Out-Null
Invoke-WebRequest -Uri $archiveUrl -OutFile $archive
$actualArchive = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualArchive -ne $archiveSha256) {
    throw "Rubber Band archive checksum mismatch: $actualArchive"
}
Expand-Archive -Path $archive -DestinationPath $extract -Force
$payload = Join-Path $extract "rubberband-$version-gpl-executable-windows"
Copy-Item (Join-Path $payload "rubberband.exe") $binDir -Force
Copy-Item (Join-Path $payload "rubberband-r3.exe") $binDir -Force
Copy-Item (Join-Path $payload "sndfile.dll") $binDir -Force
Copy-Item (Join-Path $payload "COPYING.txt") $licenseDir -Force
$sourceArchive = Join-Path $licenseDir "rubberband-$version.tar.bz2"
Invoke-WebRequest -Uri $sourceUrl -OutFile $sourceArchive
$actualSource = (Get-FileHash $sourceArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSource -ne $sourceSha256) {
    throw "Rubber Band source checksum mismatch: $actualSource"
}

& (Join-Path $binDir "rubberband.exe") --version
