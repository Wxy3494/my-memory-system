param([string]$OutputName = ('stage5-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
$ErrorActionPreference = 'Stop'
if ($OutputName -notmatch '^[A-Za-z0-9_-]+$') { throw 'OutputName 只能包含字母、数字、下划线和连字符' }
$docker = 'docker.exe'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    $output = Join-Path 'docs/evaluation' ($OutputName + '.json')
    if (Test-Path -LiteralPath $output) { throw '结果已存在，请使用新的 OutputName，保留原始基线' }
    & $docker compose exec -T api mkdir -p /tmp/rag-evals
    if ($LASTEXITCODE -ne 0) { throw 'API 容器不可用，请先启动 Docker 和 Compose' }
    & $docker compose cp ./evals/. api:/tmp/rag-evals
    if ($LASTEXITCODE -ne 0) { throw '复制评估脚本失败' }
    & $docker compose exec -T api python /tmp/rag-evals/test_scoring.py
    if ($LASTEXITCODE -ne 0) { throw '评分器测试失败，停止评估' }
    & $docker compose exec -T api python /tmp/rag-evals/run.py --output ('/tmp/' + $OutputName + '.json')
    $runExit = $LASTEXITCODE
    & $docker compose cp ('api:/tmp/' + $OutputName + '.json') $output
    if ($runExit -ne 0 -or $LASTEXITCODE -ne 0) { throw '评估未完成；如已生成部分结果，请保留以供排查' }
    Write-Output ('评估结果：' + $output)
} finally { Pop-Location }
