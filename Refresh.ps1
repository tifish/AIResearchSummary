$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$WorkspaceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $WorkspaceRoot

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$SkillRoot = Join-Path $WorkspaceRoot ".agents\skills\economic-futures-summary"
$DiscoverScript = Join-Path $SkillRoot "scripts\discover_articles.py"
$RenderScript = Join-Path $SkillRoot "scripts\render_site.py"
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

if ($newCount -eq 0) {
    Write-Host ""
    Write-Host "No new articles. Rendering summary site..."
    Invoke-CheckedNative python $RenderScript
    Write-Host ""
    Write-Host "Done. Open site\index.html to view the summary page."
    exit 0
}

$conclusionLabel = ([string][char]0x7ED3) + ([string][char]0x8BBA) + ([string][char]0xFF1A)
$keyDataLabel = ([string][char]0x5173) + ([string][char]0x952E) + ([string][char]0x6570) + ([string][char]0x636E) + ([string][char]0xFF1A)

$prompt = @"
Use `$economic-futures-summary to update the AI research summary site in this workspace.

Read the discovery JSON file at:
$DiscoveryJson

Process only the new article candidates represented by new_count and the articles array. For each new article, run extract_article.py to fetch metadata and article text, then update site/articles.json without modifying existing records. Generate summary_zh and value_zh in Chinese. summary_zh must include the labels "$conclusionLabel" for the conclusion and "$keyDataLabel" for key data. value_zh should explain why the article is worth reading. Finally run render_site.py to regenerate site/index.html. Report the number of newly added articles when finished.
"@

Write-Host ""
Write-Host "Found $newCount new articles. Running Codex to extract, summarize, update data, and render the site..."
$prompt | & codex exec --cd $WorkspaceRoot --skip-git-repo-check --sandbox danger-full-access --ask-for-approval never -
$codexExitCode = $LASTEXITCODE
if ($codexExitCode -ne 0) {
    throw "Codex update failed with exit code $codexExitCode."
}

Write-Host ""
Write-Host "Codex update completed."
