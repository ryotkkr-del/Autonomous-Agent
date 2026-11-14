param([switch]$Launch)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Fail([string]$Message) { Write-Host $Message -ForegroundColor Red; exit 1 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'Git for Windows が必要です。' }
if (-not (Test-Path '.git')) { Fail 'GitHubからcloneしたフォルダで実行してください。' }
$remote = (& git remote get-url origin 2>$null)
if ($LASTEXITCODE -ne 0 -or $remote -notmatch '(^https://github\.com/ryotkkr-del/Autonomous-Agent(?:\.git)?$|^git@github\.com:ryotkkr-del/Autonomous-Agent(?:\.git)?$)') { Fail 'originが指定のリポジトリではありません。' }
if ((& git branch --show-current).Trim() -ne 'main') { Fail 'main以外のブランチは自動更新しません。' }
$changes = @(& git status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $changes.Count -gt 0) { Fail 'ローカル変更があるので更新を停止しました。' }
& git fetch origin main --prune
if ($LASTEXITCODE -ne 0) { Fail 'GitHubへの接続に失敗しました。' }
$localSha = (& git rev-parse HEAD).Trim()
$remoteSha = (& git rev-parse origin/main).Trim()
if ($localSha -ne $remoteSha) {
  & git merge-base --is-ancestor HEAD origin/main
  if ($LASTEXITCODE -ne 0) { Fail '履歴が分岐しています。' }
  & git merge --ff-only origin/main
  if ($LASTEXITCODE -ne 0) { Fail '同期できませんでした。' }
  Write-Host '更新しました。' -ForegroundColor Green
} else { Write-Host '最新版です。' -ForegroundColor Green }
if ($Launch) {
  $launcher = Join-Path $PSScriptRoot 'start.ps1'
  $main = Join-Path $PSScriptRoot 'gui.py'
  if (-not (Test-Path $launcher) -or -not (Test-Path $main)) {
    Fail 'アプリ本体がまだGitHubにありません。v1.1の初回セットアップを行ってください。'
  }
  & $launcher
}
