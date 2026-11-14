# Autonomous Agent

Windows向けの自律AIエージェント（Ollama + Python + SQLite + optional Codex）。

## 現在の状態（重要）

**アプリ本体はGitHubへまだ登録されていません。** 現在このリポジトリにあるのは同期設定とCIです。
v1.1の**初回セットアップZIP**をこのChatGPTの会話から取得し、Windowsで展開してください。

1. Git for Windows と Python 3.11以降を用意します。
2. ZIPの中の `初回セットアップ.bat` をダブルクリックします。
3. スクリプトは55件の既存テストを実行し、本体をGitHubへpushしてから `%USERPROFILE%\Autonomous-Agent` にcloneします。
4. その後は、clone先の `更新して起動.bat` で最新版を取得しアプリを起動します。

GitHub認証やGitの `user.name` / `user.email` 設定が必要な場合があります。**初回pushが完了するまでは更新して起動しても本体を起動できません。**

## 更新の方針

- GitHubの `main` を正本とし、Windows側は起動時にfast-forwardのみ更新します。
- ローカルの未コミット変更や履歴の分岐があれば同期を停止します。強制上書きはしません。
- `state.sqlite3*`、`workspace/`、`.env` はGit管理対象外です。
- GitHub ActionsでWindows/Linux、Python 3.11/3.13の単体テストを実行します。
- Windows/Ollama/Codexの実機での動作はまだ未検証です。
- Pythonテストの実行はOSレベルのサンドボックスではありません。

