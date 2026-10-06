param([string]$Docker = '', [string]$Image = 'ai-customer-service-rag:stage4')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Docker) {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { $Docker = $command.Source }
    else { $Docker = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe' }
}
if (-not (Get-Command $Docker -ErrorAction SilentlyContinue)) {
    throw 'Docker unavailable; start Docker Desktop and pass -Docker with its executable path.'
}
# Use the installed Linux dependencies and current source; no .env or model call.
foreach ($suite in @('tests', 'evals')) {
    & $Docker run --rm --network none --workdir /workspace `
        --mount "type=bind,source=$projectRoot\app,target=/workspace/app,readonly" `
        --mount "type=bind,source=$projectRoot\tests,target=/workspace/tests,readonly" `
        --mount "type=bind,source=$projectRoot\evals,target=/workspace/evals,readonly" `
        --mount "type=bind,source=$projectRoot\docs\faq.md,target=/workspace/docs/faq.md,readonly" `
        $Image python -m unittest discover -s $suite -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed: $suite" }
}
