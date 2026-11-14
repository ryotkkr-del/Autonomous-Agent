param([switch]$Launch)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Fail([string]$Message) { Write-Host $Message -ForegroundColor Red; exit 1 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'Git for Windows をインストールしてください。' }
if (-not (Test-Path -LiteralPath '.git')) { Fail 'GitHubからcloneしたフォルダではありません。' }
$remote = (git remote get-url origin 2>$null)
if ($LASTEXITCODE -ne 0 -or $remote -notmatch '(^https://github\.com/ryotkkr-del/Autonomous-Agent(?:\.git)?$|^git@github\.com:ryotkkr-del/Autonomous-Agent(?:\.git)?$)') { Fail 'originが指定のリポジトリではありません。' }
$branch = (git branch --show-current).Trim()
if ($branch -ne 'main') { Fail "main以外のブランチです: $branch" }
$changes = @(git status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $changes.Count -gt 0) { Fail 'ローカル変更があります。更新を中止しました。' }
git fetch origin main --prune
if ($LASTEXITCODE -ne 0) { Fail 'GitHubに接続できません。' }
$localSha = (git rev-parse HEAD).Trim()
$remoteSha = (git rev-parse origin/main).Trim()
if ($localSha -ne $remoteSha) {
  git merge-base --is-ancestor HEAD origin/main
  if ($LASTEXITCODE -ne 0) { Fail '履歴が分岐しています。手動で確認してください。' }
  git merge --ff-only origin/main
  if ($LASTEXITCODE -ne 0) { Fail '更新に失敗しました。' }
  Write-Host '更新完了。' -ForegroundColor Green
} else { Write-Host '最新版です。' -ForegroundColor Green }
if ($Launch) { & (Join-Path $PSScriptRoot 'start.ps1') }
