[CmdletBinding()]
param(
    [string]$DatasetRoot = "training-data/procurement-dataset.v1",
    [string]$ContainerName = "training-data",
    [string]$ConnectionString,
    [string]$EnvFile,
    [switch]$Overwrite,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ConnectionStringFromEnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        throw ".env file not found at: $Path"
    }

    $line = Select-String -Path $Path -Pattern '^AZURE_STORAGE_CONNECTION_STRING=' | Select-Object -First 1
    if (-not $line) {
        throw 'AZURE_STORAGE_CONNECTION_STRING not found in env file'
    }

    $value = $line.Line.Substring('AZURE_STORAGE_CONNECTION_STRING='.Length).Trim()
    if (-not $value) {
        throw 'AZURE_STORAGE_CONNECTION_STRING is empty in env file'
    }

    return $value
}

function Get-SidecarInfo {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )

    if ($File.Name.EndsWith('.pdf.labels.json', [System.StringComparison]::OrdinalIgnoreCase)) {
        return [PSCustomObject]@{
            SidecarType = 'labels'
            PdfName = $File.Name.Substring(0, $File.Name.Length - '.labels.json'.Length)
        }
    }

    if ($File.Name.EndsWith('.pdf.ocr.json', [System.StringComparison]::OrdinalIgnoreCase)) {
        return [PSCustomObject]@{
            SidecarType = 'ocr'
            PdfName = $File.Name.Substring(0, $File.Name.Length - '.ocr.json'.Length)
        }
    }

    return $null
}

$procurementRoot = Split-Path -Parent $PSScriptRoot

$resolvedDatasetRoot = if ([System.IO.Path]::IsPathRooted($DatasetRoot)) {
    $DatasetRoot
} else {
    Join-Path $procurementRoot $DatasetRoot
}

if (-not (Test-Path $resolvedDatasetRoot)) {
    throw "Dataset root not found: $resolvedDatasetRoot"
}

$resolvedEnvFile = if ($EnvFile) {
    if ([System.IO.Path]::IsPathRooted($EnvFile)) {
        $EnvFile
    } else {
        Join-Path $procurementRoot $EnvFile
    }
} else {
    Join-Path $procurementRoot '.env.local'
}

$effectiveConnectionString = $ConnectionString
if (-not $effectiveConnectionString) {
    $effectiveConnectionString = Get-ConnectionStringFromEnvFile -Path $resolvedEnvFile
}

$env:AZURE_STORAGE_CONNECTION_STRING = $effectiveConnectionString

if ($effectiveConnectionString -match 'AccountName=([^;]+)') {
    Write-Host ('Using storage account: ' + $matches[1])
}

$sidecarFiles = Get-ChildItem -Path $resolvedDatasetRoot -Recurse -File |
    Where-Object {
        $_.Name.EndsWith('.pdf.labels.json', [System.StringComparison]::OrdinalIgnoreCase) -or
        $_.Name.EndsWith('.pdf.ocr.json', [System.StringComparison]::OrdinalIgnoreCase)
    }

if (-not $sidecarFiles -or $sidecarFiles.Count -eq 0) {
    Write-Host "No sidecar files found under: $resolvedDatasetRoot"
    return
}

$blobCache = @{}
$uploadedCount = 0
$skippedCount = 0
$missingMatchCount = 0
$ambiguousCount = 0
$existingCount = 0
$overwriteValue = if ($Overwrite) { 'true' } else { 'false' }

Write-Host ('Found sidecar files: ' + $sidecarFiles.Count)

foreach ($sidecar in $sidecarFiles) {
    $info = Get-SidecarInfo -File $sidecar
    if (-not $info) {
        continue
    }

    $relativePath = [System.IO.Path]::GetRelativePath($resolvedDatasetRoot, $sidecar.FullName)
    $relativeDir = [System.IO.Path]::GetDirectoryName($relativePath)
    if (-not $relativeDir) {
        $relativeDir = ''
    }

    $prefix = if ($relativeDir) {
        ($relativeDir -replace '\\', '/') + '/'
    } else {
        ''
    }

    if (-not $blobCache.ContainsKey($prefix)) {
        $blobList = az storage blob list --connection-string $effectiveConnectionString --container-name $ContainerName --prefix $prefix --query "[].name" -o tsv
        if (-not $blobList) {
            $blobList = @()
        }

        $blobCache[$prefix] = @($blobList)
    }

    $blobsInPrefix = $blobCache[$prefix]
    $pdfMatches = @($blobsInPrefix | Where-Object {
        $_.EndsWith($info.PdfName, [System.StringComparison]::OrdinalIgnoreCase)
    })

    if ($pdfMatches.Count -eq 0) {
        $missingMatchCount++
        Write-Warning ("No blob PDF match for local sidecar: " + $relativePath)
        continue
    }

    if ($pdfMatches.Count -gt 1) {
        $ambiguousCount++
        Write-Warning ("Ambiguous blob PDF matches for local sidecar: " + $relativePath)
        $pdfMatches | ForEach-Object { Write-Warning ("  candidate: " + $_) }
        continue
    }

    $matchedPdfBlob = $pdfMatches[0]
    $targetBlob = if ($info.SidecarType -eq 'labels') {
        "$matchedPdfBlob.labels.json"
    } else {
        "$matchedPdfBlob.ocr.json"
    }

    $targetExists = @($blobsInPrefix | Where-Object { $_ -eq $targetBlob }).Count -gt 0
    if ($targetExists -and -not $Overwrite) {
        $existingCount++
        $skippedCount++
        Write-Host ("Skip existing (use -Overwrite): " + $targetBlob)
        continue
    }

    $blobPdfFilename = ($matchedPdfBlob -split '/')[-1]

    if ($DryRun) {
        Write-Host ("[DRY-RUN] Upload " + $relativePath + " -> " + $targetBlob)
        if ($info.SidecarType -eq 'labels') {
            Write-Host ("[DRY-RUN]   document field -> " + $blobPdfFilename)
        }
        continue
    }

    $uploadSource = $sidecar.FullName
    $tempFile = $null
    if ($info.SidecarType -eq 'labels') {
        $json = Get-Content -Raw -Path $sidecar.FullName | ConvertFrom-Json
        $json.document = $blobPdfFilename
        $tempFile = [System.IO.Path]::GetTempFileName()
        $json | ConvertTo-Json -Depth 20 | Set-Content -Path $tempFile -Encoding UTF8
        $uploadSource = $tempFile
    }

    try {
        az storage blob upload `
            --connection-string $effectiveConnectionString `
            --container-name $ContainerName `
            --name $targetBlob `
            --file $uploadSource `
            --overwrite $overwriteValue | Out-Null
    } finally {
        if ($tempFile -and (Test-Path $tempFile)) {
            Remove-Item -Path $tempFile -Force
        }
    }

    $uploadedCount++
    Write-Host ("Uploaded: " + $relativePath + " -> " + $targetBlob)
    if ($info.SidecarType -eq 'labels') {
        Write-Host ("  document field set to: " + $blobPdfFilename)
    }

    if (-not $blobsInPrefix.Contains($targetBlob)) {
        $blobCache[$prefix] = @($blobsInPrefix + $targetBlob)
    }
}

Write-Host '=== Summary ==='
Write-Host ('Uploaded: ' + $uploadedCount)
Write-Host ('Skipped: ' + $skippedCount)
Write-Host ('Already existed: ' + $existingCount)
Write-Host ('Missing PDF matches: ' + $missingMatchCount)
Write-Host ('Ambiguous PDF matches: ' + $ambiguousCount)