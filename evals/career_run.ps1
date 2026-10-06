param([string]$RunName = ('career-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
$ErrorActionPreference = 'Stop'
if ($RunName -notmatch '^[A-Za-z0-9_-]+$') { throw 'RunName 只能包含字母、数字、下划线和连字符' }
$docker = 'docker.exe'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $folder = Join-Path 'docs/evidence' $RunName
    if (Test-Path -LiteralPath $folder) { throw '结果目录已存在，选择新的 RunName 保留旧结果' }
    & $docker compose exec -T api mkdir -p /tmp/rag-evals
    if ($LASTEXITCODE -ne 0) { throw 'API 不可用；先恢复 Docker 并启动 Compose' }
    New-Item -ItemType Directory -Path $folder | Out-Null
    & $docker compose cp ./evals/. api:/tmp/rag-evals
    if ($LASTEXITCODE -ne 0) { throw '复制脚本失败' }
    & $docker compose exec -T api python /tmp/rag-evals/test_scoring.py
    if ($LASTEXITCODE -ne 0) { throw '评分器验证失败' }
    & $docker compose exec -T api python /tmp/rag-evals/career_run.py --output ('/tmp/' + $RunName + '.json')
    $runExit = $LASTEXITCODE
    & $docker compose cp ('api:/tmp/' + $RunName + '.json') (Join-Path $folder 'raw.json')
    if ($runExit -ne 0 -or $LASTEXITCODE -ne 0) { throw '本轮未完成；如有部分 raw.json 请保留排查' }
    & $docker compose logs --no-log-prefix api | Set-Content -LiteralPath (Join-Path $folder 'server-log.jsonl') -Encoding utf8
    & $docker inspect rag-stage4-api-1 --format '{{.Image}}' | Set-Content -LiteralPath (Join-Path $folder 'image.txt') -Encoding utf8
    Write-Output ('原始证据：' + $folder)
} finally { Pop-Location }
