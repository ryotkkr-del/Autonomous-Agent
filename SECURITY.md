# Autonomous Agent — セキュリティ設計と監査記録

更新日: 2026-11-15

## 適用範囲

このアプリはWindowsカーネルやドライバーを直接操作するプログラムではありません。Pythonの通常のユーザー権限で動作するローカル自律エージェントです。**OSレベルのサンドボックスは生成されたPythonテストを実行するDockerコンテナにだけ適用**します。エージェント自体、Ollama、Git、Codex CLI、GUI、WebアクセスはDocker内には入りません。

## 実施済み対策

- 生成Pythonテストの実行にはDocker Linuxコンテナを必須化。Dockerが使えなければ実行を拒否し、ホスト実行へフォールバックしません。
- Linuxコンテナは `--network none`、コンテナの読み取り専用ルート、読み取り専用の一時スナップショット、非rootユーザー、Linux capabilities削除、権限昇格禁止、CPU/メモリ/PID数制限を適用。
- 実行に渡す一時スナップショットは通常ファイルだけに制限。隠しファイル、機密らしい名前、特定の拡張子以外、シンボリックリンク、ハードリンクを除外・拒否し、ファイル数と総容量を制限。
- ホストワークスペースの編集は原則ジョブ専用領域に制限。更新時の一時ファイルはランダムな排他作成、初回バックアップは排他作成し、既存のバックアップシンボリックリンクを拒否。
- ローカルGitチェックポイントで `.env` や `credentials.json` など機密情報を疑うファイル名がある場合は処理を拒否（内容中の秘密を検知できるわけではない）。
- Dockerのイメージダウンロードにはユーザーの明示的な許可が必要。アプリからDocker DesktopのインストールやOS設定の変更は実施しない。
- Docker実行イメージとCI内のGitHub Actionsは不変のSHA参照に固定。更新はDependabotのPRと隔離テストの確認を経て行う。
- CodeQLを`main`への更新・PR・週次で実行し、結果はGitHubのSecurityタブで確認する。静的解析は実機隔離試験や人手レビューの代替ではない。

## 残るリスク

| 領域 | 注意点 |
|---|---|
| エージェント本体のファイルアクセス | Python実行プロセスはWindowsユーザー権限。ローカルの別プロセスによる競合、ハードリンク、特殊なWindowsファイル機能を含むあらゆる攻撃を完全には防げません |
| Ollama / Web | 目標やコードがローカルOllamaへ渡ります。Web検索を許可すると検索語が外部へ送信されます。悪意ある検索結果に対するプロンプト注入耐性は完全ではありません |
| Docker | Linuxカーネル、Docker daemon、Docker Desktop/WSL2、ランタイムの未知の脆弱性や設定の違いは残ります。DockerコンテナにDockerソケットや他のホストパスを渡さないでください |
| テストの品質 | テストの合格は成果物の正しさや安全性を保証しません。ソースコード内に埋め込まれた秘密情報も、ファイル名フィルターだけでは防げません |
| Git / Codex | Git履歴は削除しても残る場合があり、内容に埋め込まれた秘密はフィルターで見逃します。Codexの明示的な手動実行はDockerテスト隔離の対象外です |
| リソース消費 | Dockerイメージ取得、コンテナ起動、Ollamaのローカル推論はメモリ・ディスク・CPUを使用します。作業はユーザーがPCを起動している間に限ります |
| Windowsでの運用 | GitHub ActionsではWindowsのPythonテストとLinuxの実Dockerテストを実施。個人PCのDocker Desktop/WSL2とOllamaとの完全な結合試験ではありません |

## 推奨する運用

1. 管理者権限で起動しない。可能なら一般ユーザーアカウントを使う。
2. 重要なファイルは別の場所にバックアップし、最初はテスト実行、Git、Web検索を無効のまま試す。
3. Docker Desktopは公式配布先から導入し、Linuxコンテナを選択する。外部Docker daemonを使わない。
4. 未確認の生成コードのテストはDocker隔離でも絶対安全ではないことを前提に扱う。特に機密情報を含むファイルをジョブ領域へ置かない。
5. 長期ジョブのスケジューラは必要な場合だけ手動で登録し、終了時は停止する。
6. 開発環境の変更後は `python -m unittest discover -s tests -q` とGitHub ActionsのDocker隔離テストを確認する。

## 検証

CIではLinux/Windows × Python 3.11/3.13のユニットテスト、Linux Docker上でホスト書き込み・ネットワーク遮断の実テストを実施します。失敗時はリリース成功とみなさずログを調査します。

セキュリティ上の問題を見つけた場合は、公開IssueにパスワードやAPIキーを投稿しないでください。

## v2.0: ファイル編集承認境界

新しいCLI/GUIジョブは、AIが提出したファイル変更をSQLiteの保留テーブルに保存し、実ファイル書き込みを実行しません。人間がファイル差分を見て承認してから、専用ワークスペースへ反映されます。却下した場合は未反映のまま破棄します。保存時の内容SHA-256を記録し、承認時に照合して外部編集による不整合を拒否します。

- **旧ジョブ:** v2.0へのDB初回移行で既存ジョブに承認制を自動適用します。保存済み成果物・履歴は変更しません。直接Python APIから作成した未保護ジョブは `protect-job` で保護してください。
- **Codex/Git:** 保護ジョブではCodexの直接実行とAIのGitチェックポイントを禁止しています。CodexそのものをDockerコンテナ内へ入れたわけではありません。
- **実行分離:** 生成PythonテストはDocker隔離のままです。ファイル編集そのものは「隔離コンテナ内でコードを修正する」のではなく、**モデルによる提案→DBへ保留→人間の承認→ホスト側の限定的なファイル更新**方式です。
- **残余リスク:** Docker、OS、同一アカウントで走る別プロセスの脆弱性、TOCTOU競合、承認した内容が悪意あるソースである可能性は残ります。ソースの安全性を自動証明するものではありません。


## v2.1 — スナップショットと複数変更の取り扱い

- 承認前の内容をSQLite BLOBに保存し、承認後に変更がない場合にだけロールバックを許可。**変更後に誰かが追記・修正したファイルは自動上書きしません**。
- 変更前バイト列は完全なバックアップの代わりにはなりません。SQLiteの損失、保存処理の失敗、強制終了などのリスクがあります。重要データには独立したバックアップを推奨。
- 一括承認は全変更のハッシュ・パス・限定的な秘密情報パターンを事前検証。通常の処理例外では適用済みのファイルの巻き戻しを試みます。ただしOSクラッシュ時などの**全ファイル原子的反映は保証しません**。
- スナップショットDBは変更前のコードや、内容中に含まれていた機密を保持します。SQLiteファイルとバックアップへのアクセス権・共有先を制限してください。
- 秘密情報の検出は高確度パターンの一部のみ。機密を含む通常の文章・ソースコードも依然としてリスクがあります。

## v2.2 — 仮想下書きとDocker検証の境界

- 新しいGUI/CLIジョブでは、AIが複数の文書・コード変更案をSQLiteの仮想オーバーレイに保存し、参照・再編集します。完了申告時は差分をまとめてレビュー待ちにします。**人間の承認まで成果物フォルダへ編集を書き込まない**設計です。
- Dockerテストを明示的に許可した場合のみ、既存ファイルと仮想下書きから一時コピーを作り、従来のLinuxコンテナに読み取り専用で渡して検証します。テスト不許可なら生成コードを実行しません。
- **隔離の限界:** Ollama・AIループ・SQLite保存・一次コピーの作成はWindows上の通常のPythonプロセスです。これは仮想の編集領域とDockerでの*テスト実行*を組み合わせた構造であり、AIエージェント本体をOSレベルで隔離するものではありません。
- 完成後の一括承認は全保留ファイルのIDを必要とし、部分反映を禁止します。拒否または衝突時はホストの成果物を変更しません。通常の途中エラー時は元に戻すよう試みますが、電源障害時の完全な原子的反映は保証しません。
- 変更案・スナップショットにはソース内容が含まれ、SQLiteと一時コピーのアクセス権管理が必要です。秘密情報パターン検出には限界があります。

## v2.3 — Ollama実測ベンチマーク

- `benchmarks/real_ollama.py` はモデルの接続先がローカルOllama HTTPエンドポイントであることを事前に確認し、外部のOllama URLを拒否します。
- 各タスクで独立した一時SQLiteとワークスペースを使用します。AIはSQLite仮想下書きで文書・コードを作成し、人間の承認なしにファイルを成果物フォルダへ反映できません。
- Web検索・Git・Codex・Pythonテスト権限は有効化されず、生成コードをホスト上でもDocker内でも実行しません。したがって**コードの実行結果を検証したベンチマークではありません**。
- スコアリングは制約の一部だけを測定します。単体テストはモデルをモックして評価器を検証するだけであり、実モデルの性能・防御性能・長時間安定性の証明ではありません。
- 実測時の出力JSONにはタスク名・エラー概要・一部実行ログ・モデル情報が入るため、共有前に確認してください。

## v2.4 — 失敗分析の安全境界

- 失敗分析はベンチマークレポートのJSONから導出するオフライン処理で、Ollama・Web・Codex・Dockerを起動せず、生成されたコードも実行しません。
- ファイル変更・自動再学習・プロンプト自己改変は行いません。改善案はMarkdownとJSONへ出力し、実施には人間の判断が必要です。
- 既存の測定レポートと同じパスを出力先へ指定した場合は、書き込む前に拒否します。
- 提案は限定的なルールに基づく仮説であり、未知の障害やログにない根本原因まで正しく特定するものではありません。レポートの入力内容と生成文書は公開前に確認してください。

## v2.5 — 実験の安全境界

追加指示は人間が選んだUTF-8テキストから明示的な実行許可を得て読み込む。実験用の判断プロンプトにのみ付加し、本番プロンプトやソースには適用しない。通常ジョブ、Git履歴、テスト実行権限は変更しない。既存結果を上書きせず、実験ごとに固有フォルダへ保存する。評価中にAI生成コードを実行しない。採用判断は人間が行う。

## v2.6 Security audit

- HTTPS fetches verify public DNS answers and pin the inspected numeric address while retaining hostname-based TLS certificate checks. Redirects and proxy use are disabled.
- Ollama requests and model preflight are restricted to local HTTP connections without automatic redirects or proxying. Localhost is normalized to loopback.
- Agent-controlled workspace paths now reject hidden files, credential-like names, Windows reserved device names, trailing spaces/dots, and hard-linked files.
- Generated Python tests remain Docker-only, and proposed edits remain subject to the existing approval gate.

Remaining risk: this is not a full OS sandbox. Races involving other local processes, Windows reparse points, credentials embedded inside ordinary source files, and bugs in the OS, TLS or Docker runtime are still possible. Use a standard user account, avoid sensitive files, and keep independent backups.

Git command hardening: Git status now requires explicit `allow_git`; protected jobs deny Git status and checkpoints. Git subprocess invocations disable `core.fsmonitor`, external diff and credential helpers. These are reductions in attack surface rather than guarantees for a malicious Git installation or repository.

## P0-4 phase 1 — fail-closed launch and independent signed-tag verification

- `sync.ps1 -Launch` does not fetch or merge GitHub `main`. Both the legacy `更新して起動.bat` and `安全に起動.bat` start installed local code without automatic updates.
- `開発版を更新して起動.bat` is strictly for development. It checks expected origin, `main`, and a clean tracked working tree, requires the exact interactive phrase `DEV-UPDATE`, and allows only a fast-forward merge. **This does not make development commits production safe.**
- `sync.ps1 -CheckReleaseTag vX.Y.Z` is a *verification-only* operation; it fetches the named Git tag and runs `release_policy.py`, which rejects nonannotated tags, failed GPG verification, unknown signers, missing external trust configuration, and malformed tag names. It does not install code.
- The allowed maintainer signing-key fingerprints must be independently validated and stored outside the Git checkout. Copying a fingerprint from the same compromised repository is not independent authentication.
- Windows PowerShell 5.1 requires UTF-8 BOM for non-ASCII script messages; the updater is saved with BOM and the Windows CI smoke test checks the safe default execution path.

**Unfinished release security:** No official automatically installed trusted release path exists yet. Release artifacts, signed manifests, CI pass verification, archive integrity, old-version rollback, and end-to-end Windows 11 verification remain P0-4 requirements. The first manual bootstrap from older copies is still a developer-controlled action, not a verified production upgrade. Full operating-system isolation is not provided.

## P0-4 stage 2: verified pre-update data snapshots

- Every explicit developer main update must finish a verified backup BEFORE any Git network fetch or merge. Missing Python, missing backup tool, an active agent lock, SQLite corruption, changed workspace files, unsafe paths, unsupported sizes, or verification failure prevents the update.
- The snapshot is stored outside the Git checkout. SQLite uses the backup API, normalized to a standalone DELETE-journal file, then verified with `PRAGMA integrity_check`. Workspace and benchmark results are copied with per-file SHA-256 checks; no previous backup is overwritten or deleted.
- Symlinks, Windows reparse points, hardlinked files and special nodes are rejected. Size limits are enforced; malformed recovery paths, traversal, Windows ADS and device names are rejected.
- Recovery only copies verified data into a new, initially nonexistent directory outside the active installation. It never overwrites an active SQLite file, workspace or Git revision.
- Snapshot files and manifests are sensitive data. SHA-256 does not authenticate against a malicious actor who can alter both files and manifests. Keep backups in a private user account area.
- The agent lock restricts concurrent agent execution, but does not establish atomic cross-file consistency against arbitrary external writers. Back up while GUI tasks and scheduled writers are stopped.

Remaining P0-4/P0-5 work: trusted Release distribution and CI/artifact verification, transactional code switching and automatic rollback, live restore with safe shutdown, power-loss/recovery tests, and user's own Windows 11 + Docker/Ollama verification.

## P0-4 stage 3 — signed Git source and exact-commit CI candidate verification

- `release_candidate.py` refuses release staging unless a stable annotated Git tag has a valid GPG signature by an independently pinned maintainer key. The trust file is outside the checkout and is never created automatically.
- The program fetches bounded CI status data from the fixed HTTPS GitHub API origin without environment HTTP proxies or redirects. It requires successful completed `push` runs for the exact signed commit on `main` for all three workflows: Python tests, behavioral benchmark and live Docker sandbox integration. Missing/mismatched/failed workflows block staging.
- Optional `--stage` materializes files from the verified Git tree using `git cat-file` blobs and validates file length and Git object ID, also recording SHA-256. The file set is strictly bounded; links, Git submodules, Windows reserved names, runtime data, path traversal and case collisions are rejected. It does not use `git checkout`, apply code, execute tests from candidate, or touch user workspace/SQLite.
- Candidate copies are placed outside the Git checkout, with a new unique folder each time. No automatic activation, background update, runtime migration or automatic rollback has been implemented.

Limitations: GitHub API CI conclusions are not independent cryptographically signed build provenance. Maintainer key rotation, workflow tampering, compromised local installation/host Git runtime, content changes after staging, and local filesystem races remain possible. Do not run the staged code manually as a substitute for a verified installer. No official signed Release is published yet; therefore this is a fail-closed foundation, not production auto-update.
