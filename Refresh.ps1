param(
    [Parameter(Position = 0)]
    [ValidateSet('codex', 'claude')]
    [string] $Agent = 'codex'
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$WorkspaceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $WorkspaceRoot

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
# Pipe UTF-8 to the agent (Windows PowerShell 5.x defaults to ASCII, which would
# mangle the Chinese prompt body read from refresh-prompt.md).
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$ScriptsDir = Join-Path $WorkspaceRoot "scripts"
$PromptFile = Join-Path $WorkspaceRoot "refresh-prompt.md"
$DiscoverScript = Join-Path $ScriptsDir "discover_articles.py"
$RenderScript = Join-Path $ScriptsDir "render_site.py"
$DiscoveryJson = Join-Path ([System.IO.Path]::GetTempPath()) "ai-research-summary-discovery.json"

function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true)]
        [string] $FilePath,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )

    & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$FilePath failed with exit code $exitCode."
    }
}

Write-Host "Discovering new AI research articles..."
$discoverOutput = & python $DiscoverScript
$discoverExitCode = $LASTEXITCODE
if ($discoverExitCode -ne 0) {
    throw "Discovery failed with exit code $discoverExitCode."
}

$discoverText = $discoverOutput -join [Environment]::NewLine
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($DiscoveryJson, $discoverText, $utf8NoBom)
Write-Host $discoverText

$discovery = Get-Content -LiteralPath $DiscoveryJson -Raw -Encoding UTF8 | ConvertFrom-Json
$newCount = [int] $discovery.new_count
$sourceErrors = @()
if ($discovery.PSObject.Properties.Name -contains "source_errors" -and $null -ne $discovery.source_errors) {
    $sourceErrors = @($discovery.source_errors)
}

if ($sourceErrors.Count -gt 0) {
    Write-Host ""
    Write-Host "Static discovery had source errors:"
    foreach ($sourceError in $sourceErrors) {
        Write-Host "  $sourceError"
    }
}

if ($newCount -eq 0 -and $sourceErrors.Count -eq 0) {
    Write-Host ""
    Write-Host "No new articles. Rendering summary site..."
    Invoke-CheckedNative python $RenderScript
    Write-Host ""
    Write-Host "Done. Open site\index.html to view the summary page."
    exit 0
}

if (-not (Test-Path -LiteralPath $PromptFile)) {
    throw "Prompt file not found: $PromptFile"
}
$promptBody = Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8

if ($sourceErrors.Count -gt 0) {
    $sourceErrorText = ($sourceErrors -join "; ")
} else {
    $sourceErrorText = "(none)"
}

$runtimeContext = @"

---

## Run context for this refresh

Follow the workflow and output rules above exactly.

The discovery script output has been written to:
$DiscoveryJson

- new_count: $newCount
- source_errors: $sourceErrorText

Process only the new article candidates represented by new_count and the articles array in that JSON.

If source_errors is not empty, inspect the affected Anthropic/OpenAI source pages with the Codex or Claude browser plugin, compare against site/articles.json, and process only genuinely new articles. Browser rendering happens in the agent environment; do not add browser automation dependencies to this project.

Report the number of newly added articles and standalone summary pages when finished.
"@

$prompt = $promptBody + $runtimeContext

Write-Host ""
if ($newCount -gt 0) {
    Write-Host "Found $newCount new articles. Running '$Agent' to extract, summarize, update data, and render the site..."
} else {
    Write-Host "Running '$Agent' to inspect sources with browser plugin support and render the site..."
}

switch ($Agent) {
    'codex' {
        $prompt | & codex exec `
            --cd $WorkspaceRoot `
            --skip-git-repo-check `
            --dangerously-bypass-approvals-and-sandbox `
            -
    }
    'claude' {
        $prompt | & claude `
            --print `
            --dangerously-skip-permissions
    }
    default {
        throw "Unknown agent '$Agent'."
    }
}

$agentExitCode = $LASTEXITCODE
if ($agentExitCode -ne 0) {
    throw "$Agent update failed with exit code $agentExitCode."
}

Write-Host ""
Write-Host "$Agent update completed."
