# P0-4 phase 1: fail closed for unattended updates.
# Default: launch installed local code without fetching GitHub main.
# -DevMain: interactive developer-only update, NOT a verified release.
# -CheckReleaseTag: check a signed Git tag, never install it.
param(
    [switch]$Launch,
    [switch]$DevMain,
    [string]$CheckReleaseTag = ''
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Fail([string]$Message) {
    Write-Host $Message -ForegroundColor Red
    exit 1
}
function CheckRepository {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail 'Git for Windows が必要です。'
    }
    if (-not (Test-Path -LiteralPath '.git')) {
        Fail 'GitHubからcloneしたフォルダで実行してください。'
    }
    $remote = (& git -c core.fsmonitor=false remote get-url origin 2>$null)
    if ($LASTEXITCODE -ne 0 -or $remote -notmatch '(^https://github\.com/ryotkkr-del/Autonomous-Agent(?:\.git)?$|^git@github\.com:ryotkkr-del/Autonomous-Agent(?:\.git)?$)') {
        Fail 'originが指定のリポジトリではありません。'
    }
}
if ($DevMain -and $CheckReleaseTag) {
    Fail '-DevMain と -CheckReleaseTag は同時に指定できません。'
}
if ($CheckReleaseTag) {
    CheckRepository
    if ($CheckReleaseTag -notmatch '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
        Fail '安定版のタグ (例: v3.0.0) のみ検証できます。'
    }
    if (-not (Test-Path -LiteralPath 'release_policy.py')) {
        Fail '署名検証プログラムがありません。更新しません。'
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Fail 'Pythonが必要です。更新しません。'
    }
    $tagRef = "refs/tags/$CheckReleaseTag"
    Write-Host '署名付きReleaseタグの候補を取得します。コードのインストールはしません。'
    & git -c core.fsmonitor=false -c credential.helper= -c core.hooksPath=NUL fetch --no-tags origin ($tagRef + ':' + $tagRef)
    if ($LASTEXITCODE -ne 0) { Fail 'Releaseタグを取得できませんでした。' }
    & python -I (Join-Path $PSScriptRoot 'release_policy.py') --tag $CheckReleaseTag --repo $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { Fail '署名または独立した信頼設定を検証できませんでした。' }
    Write-Host '署名付きGitタグの検証のみ成功。CI合格や配布物の検証、インストールは未実装です。' -ForegroundColor Yellow
    exit 0
}
if ($DevMain) {
    CheckRepository
    $branch = (& git -c core.fsmonitor=false branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') {
        Fail 'main以外のブランチは開発版更新しません。'
    }
    $changes = @(& git -c core.fsmonitor=false status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0 -or $changes.Count -gt 0) {
        Fail 'ローカル変更があるため開発版更新を拒否しました。'
    }
    Write-Host '注意: mainは署名付きReleaseではなく、正式運用には使用できません。' -ForegroundColor Yellow
    Write-Host '未検証コードが取り込まれ、PC上で実行される可能性があります。'
    $answer = Read-Host '危険性を理解して開発版を更新する場合のみ DEV-UPDATE と入力'
    if ($answer -cne 'DEV-UPDATE') {
        Fail '開発版更新はキャンセルされました。'
    }
    & git -c core.fsmonitor=false -c credential.helper= -c core.hooksPath=NUL fetch origin main --prune
    if ($LASTEXITCODE -ne 0) { Fail 'GitHubへの接続に失敗しました。' }
    $localSha = (& git -c core.fsmonitor=false rev-parse HEAD).Trim()
    $remoteSha = (& git -c core.fsmonitor=false rev-parse origin/main).Trim()
    if ($localSha -ne $remoteSha) {
        & git -c core.fsmonitor=false merge-base --is-ancestor HEAD origin/main
        if ($LASTEXITCODE -ne 0) {
            Fail '履歴が分岐しているか、mainが過去のコミットに戻っています。更新拒否。'
        }
        & git -c core.fsmonitor=false -c core.hooksPath=NUL merge --ff-only origin/main
        if ($LASTEXITCODE -ne 0) {
            Fail ('開発版更新に失敗しました。更新前のコミット: ' + $localSha)
        }
        Write-Host ('開発版を更新しました。更新前: ' + $localSha) -ForegroundColor Yellow
    } else {
        Write-Host '開発版mainに変更はありません。'
    }
} else {
    Write-Host '安全起動: mainの自動取得・更新は停止中です。' -ForegroundColor Yellow
    Write-Host '正式な署名付きRelease更新が完成するまで、インストール済みコードを起動します。'
    Write-Host '開発版を更新する場合は「開発版を更新して起動.bat」を使ってください。'
}
if ($Launch) {
    $launcher = Join-Path $PSScriptRoot 'start.ps1'
    $main = Join-Path $PSScriptRoot 'gui.py'
    if (-not (Test-Path -LiteralPath $launcher) -or -not (Test-Path -LiteralPath $main)) {
        Fail 'ローカルアプリ本体が見つかりません。起動しません。'
    }
    & $launcher
    if ($LASTEXITCODE -ne 0) { Fail 'アプリの起動に失敗しました。' }
}
