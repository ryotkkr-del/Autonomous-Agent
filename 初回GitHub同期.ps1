$ErrorActionPreference = 'Stop'
$repo = 'https://github.com/ryotkkr-del/Autonomous-Agent.git'
$dest = Join-Path $env:USERPROFILE 'Autonomous-Agent'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git for Windows をインストールしてください。' }
if (Test-Path $dest) { throw "既に $dest が存在します。既存フォルダは削除しません。" }
git clone $repo $dest
if ($LASTEXITCODE -ne 0) { throw 'git clone に失敗しました。' }
Write-Host "同期フォルダ: $dest" -ForegroundColor Green
if (-not (Test-Path (Join-Path $dest 'agent.py'))) { Write-Warning 'アプリ本体が未登録です。まずv1.0をGitHubへアップロードしてください。' }
