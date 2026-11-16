# Autonomous Agent v2.6

> **正式運用はまだ未達です。** 現在は開発・検証版です。ユーザー指定の優先度P0→P1→P2に沿って進めています。達成状況、未検証項目と次の作業は [ROADMAP_PROGRESS.md](ROADMAP_PROGRESS.md) を参照してください。P0-4の安全対策により、`更新して起動.bat` は現在**ローカル版を起動するだけ**でGitHubのmainを自動取得しません。開発版mainの更新は別の明示的な操作が必要です。

Windows用のローカル自律AIエージェント。**GitHubの`main`にアプリ本体とGUIを公開済み**です。既存のv1.1以前のコード・SQLiteデータ形式を引き継いでいます。

## セットアップ（ZIPを毎回ダウンロードする必要はありません）

WindowsにPython 3.11以降、Git for Windows、Ollamaをインストールしてください。

```powershell
git clone https://github.com/ryotkkr-del/Autonomous-Agent.git
cd Autonomous-Agent
ollama pull gemma3:4b
python agent.py doctor
python gui.py
```

以後は **`安全に起動.bat`** または従来の **`更新して起動.bat`** をダブルクリックすると、インストール済みのGUIを起動します。P0-4完了まで未検証の`main`を自動取得しません。開発版を更新する場合に限り **`開発版を更新して起動.bat`** を使い、警告を読んで `DEV-UPDATE` と入力する必要があります。

すでにGitHubからcloneしている人は、既存フォルダをそのまま使えます。ローカル起動だけなら `安全に起動.bat`、未検証の開発版mainの手動更新は `開発版を更新して起動.bat` を使用します。初回用の`GitHubへアップロード.ps1`や`初回セットアップ.bat`は**現在不要**です（旧版の説明が残っている場合は使わないでください）。

## v1.2の新機能

- **自律的な計画見直し:** 原則8ステップごとに更新案を検討し、過去の完了タスク・成果物要件を残しつつ計画を更新。履歴をSQLiteに保存。GUIの「計画を見直す」から手動実行もできます。
- **自動Web検索:** GUIの「自動Web検索を許可」、または`python agent.py allow-search 1`でジョブごとに有効化。Bing RSSを利用する読み取り専用検索で、検索先へのクエリ送信を伴います。検索結果から外部ページは自動訪問しません。URL本文を読むには別途明示的な許可が必要です。検索サービスの仕様やアクセス制限により動作しない場合があります。
- **自律コーディング強化:** `search_code`でファイル内検索、`replace_in_file`で一意な一致箇所のみ部分置換。ファイルのバックアップ、静的検査、許可制のテスト、修正履歴を利用します。任意のシェル実行や無制限の依存インストールには対応していません。

## コマンド例

```powershell
python agent.py new "Pythonの学習ツールを作りテストで改善する"
python agent.py allow-search 1
python agent.py run 1 --steps 8
python agent.py replan 1
python agent.py tasks 1
```

## 制限と安全性

本体は無料ローカル推論を利用します。Codexは明示的な許可による手動実行のみで、ChatGPT Plus利用枠の対象です。AIが生成したPythonテストはDocker Linuxコンテナ内でのみ実行し、Dockerが利用できない場合は実行を拒否します。コンテナ隔離も完全な安全保証ではありません。Windows実機でのOllama・Docker Desktop・GUIの結合確認はまだ必要です。GitHub Actionsのテスト結果は最新版の各実行記録を確認してください。

ユーザーのジョブデータ（`workspace/`、`state.sqlite3*`）と秘密情報はGitHubへアップロードしません。

---

## 以前の開発履歴・詳細仕様

# Autonomous Agent v1.0 — 状況が分かるWindows GUI

v0.9のエージェント本体、SQLiteデータ形式、コマンドライン機能はそのまま維持したUI更新です。Python 3.11以降・Ollamaが必要です。

## 使い方

1. ZIPを展開し、`起動.bat`をダブルクリックします。
2. 初回は「接続・環境を確認」を選び、Ollamaの起動とモデルの準備を確認します（モデルは `ollama pull gemma3:4b`）。
3. 目標を登録し、一覧から選択して「開始 / 再開」を押します。
4. 「現在の状況」で停止理由、計画タスクの**手動設定状態**、成果物数、最後の操作を確認します。
5. 「計画の一覧」「修正の記録」「診断の履歴」から必要な情報を参照できます。
6. 「要確認」のジョブは履歴を調べてから「停止状態の解除」を押します。解除だけでは再開しません。

### v0.9からの改善

- 停止理由や一部操作名を分かりやすい日本語で表示
- 選択ジョブの直近操作、計画タスク数、成果物数を表示（成果物数は簡易カウント）
- 約2秒ごとにジョブ一覧を更新し、外部の定期実行の更新も反映
- 計画・修正記録・診断履歴に画面からアクセス
- 停止状態の解除を画面から実行可能
- 実行中に「開始 / 再開」を押しても、停止ファイルを消さない
- ウィンドウの初期サイズを拡大

### 旧版の保存データ

v0.9の `state.sqlite3` と `workspace` を組として、新フォルダにコピーして引き継いでください。コピー前に旧エージェントとタスクスケジューラの実行を止めてください。`state.sqlite3-wal`などがある場合はSQLite書き込みが終わってからコピーします。

### 注意

- 「計画：n/m」は**計画タスクの記録上の状態**であり、AIが自動判定した進捗率ではありません。
- 生成ファイル数はルートと1階層下だけを表示する簡易表示です。ファイル内容の品質を示しません。
- 一時停止は現在進行中の操作が終わった時点で反映されます。
- テストを許可すると、テストコードはWindowsユーザーの権限で動きます。OSサンドボックスはありません。
- Codexは自動実行しません。Plusの利用枠内でCLIから明示的に使います。
- Windows上の実際のGUI・Ollama・Codexの動作は未検証です。Linux上で55件の単体テストが成功しました。
- 通常ChatGPTチャットは外部プログラムから無料APIとして呼び出せません。

---

# Autonomous Agent v0.9 — Windowsデスクトップ版

**v0.8のエージェント本体は維持し、操作を簡単にする画面（Tkinter）を追加したバージョンです。**
Python 3.11以降が必要です。追加のpipインストールはありません（Pythonに標準添付されるTkinterを利用）。

## はじめて使う（Windows）

1. このZIPを任意のフォルダに展開してください。ZIP内部で直接実行しないでください。
2. Python 3.11以降、Ollamaをインストールしてください。Pythonのインストール時はTkinter（tcl/tk）も有効にしてください。
3. Ollamaを起動し、PowerShellで **`ollama pull gemma3:4b`** を一度実行してください。
4. **`起動.bat` をダブルクリック**してください。GUIが開きます（`start.ps1`でも起動可能）。
5. 「接続・環境を確認」でOllama接続を確認し、目標を入力して「目標を登録」→「開始 / 再開」を押します。
6. 「成果物を開く」で生成されたファイルを確認できます。終了後は再度「開始 / 再開」で続行できます。

画面にはジョブ一覧と現在のステップ数が表示されます。「■ 一時停止」は**現在の操作が終わった後**に停止します。現在の操作が長引く場合、直ちに中断するわけではありません。実行時は1回1〜30ステップ、デフォルト8です。

### 画面操作だけでできること

- 目標の登録、実行、停止、履歴の参照、成果物フォルダの表示
- ChatGPT通常チャット向けレポート作成とクリップボードへのコピー（**貼り付け前に秘密情報の有無を確認**）
- 参照を許可するHTTPS URLの登録（信頼できる公開ページだけにしてください）
- ジョブごとのGitチェックポイント許可とPythonテスト実行許可
- Python / Ollama / Codexの接続状況確認

**危険性のある設定は初期状態で無効です。** テストの許可には確認画面があります。Pythonテストは同じWindowsユーザーの権限で動き、OSレベルのサンドボックスではありません。

### 保存データの移行（v0.8 → v0.9）

1. 旧エージェントと登録済み定期タスクを停止してから、v0.8のフォルダ内の `state.sqlite3` と `workspace` フォルダをバックアップします。
2. v0.9の展開先へこの2つを**セットで**コピーしてください。DBに `-wal` / `-shm` がある場合は、実行中のプロセスを完全に終了してからコピーしてください。
3. `起動.bat`を実行してください。古いジョブも一覧に表示されます。データベースを作り直す必要はありません。
4. v0.8のタスクスケジューラ登録とv0.9を**同時起動しない**でください。必要なら旧登録を解除してから再登録してください。

### 注意と現在の限界

- GUIを閉じても、すでに起動中のエージェントが直ちに止まるとは限りません。停止ボタンを押し、状態が落ち着いてから終了してください。
- OllamaやCodexの実機動作・Windows上の画面起動はこの環境では検証していません。テストはLinuxで実行しています。
- 通常のChatGPTチャットを無料APIとして呼び出すものではありません。ChatGPTレポートは手動で貼り付ける方式です。
- CodexはGUIから勝手に起動しません。従来どおりCLIの `python agent.py codex 1 --confirm` でのみ利用できます。
- 処理内容と安全性の制限はv0.8の本体に準じます。Web検索エンジン、自動課金、自動PC全体操作は含みません。

## テスト

```powershell
python -m unittest discover -s tests -v
```

Linux / Python 3.13で旧46件+GUIヘルパー4件の計50件を実行し成功。GUIの実画面とWindows/Ollama連携の手動確認は未実施です。

---

## v0.8の機能・CLIリファレンス

# Autonomous Agent v0.8 — Windows / Ollama / Codex / SQLite

v0.7の実装を引き継いだ、ローカル優先の中断・再開可能な自律エージェント。Python 3.11+、追加のpipパッケージ不要。通常ChatGPTチャットは無料のプログラムAPIとして呼び出せないため、`chat-report`経由で人間がレビューする構成です。

## v0.8 の追加改善

- **優先度付きタスクボード**：既存の `plan.tasks` をSQLiteの `plan_tasks` に保存します。状態は `todo` / `doing` / `done` / `blocked`、優先度は1〜5。設定内容は実行・再起動後も保持され、次のOllama判断プロンプトに渡されます。**タスク状態の変更は手動**です（AIによる完了判定・自動優先度変更はまだ実装していません）。既存ジョブの計画も、次回 `run` 時にタスクボードへ移行します。
- **原因仮説の比較**：失敗したテストログをもとに、Ollamaが最大3件の原因仮説、根拠、安全な確認案、優先度をJSONで提案。`diagnoses` テーブルに永続保存します。**提案は表示・保存のみで、コマンドやテストは自動実行しません**。
- **修正時の参照情報を強化**：直近の診断仮説と優先度付きタスクボードをOllamaの次アクション判断に含めます。診断後の修正成功はモデルとテストに依存します。
- **検証**：旧40件＋新6件、合計46件のPython単体テストに成功（Linux上）。Windows実機のOllama/Codex連携は未検証です。

### 新しいコマンド

```powershell
python agent.py tasks 1
python agent.py task 1 2 --priority 5 --state doing --note "優先して実装"
python agent.py diagnose 1
python agent.py diagnoses 1
python agent.py run 1 --steps 8
```

`diagnose` は**直近のテスト実行が失敗している場合のみ**利用可能で、Ollamaが起動している必要があります。原因仮説は検証前の提案であり、事実として確定しません。`tasks` コマンドは初回計画生成後に利用可能です。

## v0.7までの主要改善（引き継ぎ）

- **完了前にテストを自動実行**：ジョブに `allow-tests` を明示設定し、`tests/test*.py` が存在する場合、AIが `finish` を宣言するとテストを必ず確認します。AIが `run_tests` 操作を忘れていても、失敗したテストを無視して完了しません。
- **無駄な再テストの削減**：PythonソースとテストのSHA-256指紋を記録。前回の自動テストからコードが変わっていなければ結果を再利用します。コードが変わると再テストします。
- **失敗をAIへ戻す**：自動テスト失敗をSQLiteのログに格納。次の判断で失敗ログを読んで修正を試みます。ただし成功を保証するものではなく、最大ステップ数や反復停止条件は維持します。
- **0件テストの誤合格防止**：テストが1件も発見されなかった場合、成功扱いにしません。
- **継承性**：v0.5のデータベース、コマンド、ジョブ別作業領域を維持します。新しいpip依存はありません。

**重要**：これはWindowsセキュリティ・サンドボックスではありません。テストの実行権限を有効にすると、テストコードはWindowsユーザー権限で動きます。AI生成コードを自動実行する前に内容を確認するか、Windows Sandbox/隔離VMなどを別途利用してください。`allow-tests` が無効なら自動テストは一切実行しません。通常ChatGPTチャットの無料自動呼び出しは行いません。

### v0.7の基本ワークフロー

```powershell
python agent.py doctor
python agent.py new "Pythonの関数とunittestテストを作成する"
python agent.py run 1 --steps 8
# 作成された workspace/jobs/1/ のテストコードを人間が確認したあとでのみ：
python agent.py allow-tests 1
python agent.py run 1 --steps 8
python agent.py history 1
python agent.py repairs 1  # 修正仮説と検証結果
```

`tests/test*.py` がジョブ専用の作業領域にあるとき、`finish` 時にPython unittestを自動実行します。失敗したらログを保存し、次のステップでローカルAIによる修正を試みます。

### v0.7追加：検証可能な修正実験ログ

- テストが失敗したあとにAIがPythonコードを書き換えた場合、修正対象・`reason` に記した原因仮説・修正前後のソース指紋・元の失敗をSQLiteの`repair_attempts`に記録します。
- 次の `run_tests` または自動テスト時に、結果を **success / repeated_failure / changed_failure** として記録します。再テストまでは `pending` です。
- 直近6件の修正実験をローカルAIに渡し、同じ失敗仮説を繰り返さないよう指示します。これはモデルへの指示であり、失敗を必ず防げる仕組みではありません。
- `python agent.py repairs JOB_ID` で修正仮説と結果を確認できます。新しいSQLiteテーブルは自動作成され、従来ジョブを削除しません。
- 注意：対象は **Pythonソース/テストの指紋が変化した編集** です。Markdownだけの編集やCodexの変更は現時点では修正実験として追跡しません。失敗の署名はテスト出力に基づく近似であり、厳密な原因分類ではありません。

## v0.5から引き継ぐもの

1. **承認URL限定のWeb調査**：ユーザーが `approve-url` した完全一致のHTTPS URLだけをエージェントが `read_url` で参照可能。リダイレクト不可、HTMLをテキスト抽出、50KB制限、12秒タイムアウト、プライベートIPの基本検査。Web本文は信用できないデータとして扱う。汎用検索エンジンではありません。
2. **Gitによるローカルチェックポイント**： `allow-git` を有効にしたジョブだけが `git_checkpoint` を使用可能。専用ワークスペースで `git init` / `add` / `commit` する。Gitリモートへの通信・pushはしない。`git_status` で確認可能。
3. **判断に権限状況を反映**：エージェントの判断プロンプトに許可済URL、Git許可、テスト許可を表示。
4. **テスト履歴の検証改善**：完了判定でジョブの最大300ステップ分の履歴を参照し、過去のテスト失敗や再テスト条件を判定（最新テストがPASSの場合に限る）。
5. **互換性維持**：v0.4の計画・ジョブ別workspace・SQLiteのテーブル・停止・ブロック・Codex手動実行は維持。

## セットアップと実行

Ollamaインストール後、PowerShellで：

```powershell
ollama pull gemma3:4b
python agent.py doctor
python agent.py new "Pythonの学習用プログラムを作成して構文を確認する"
python agent.py run 1 --steps 8
python agent.py status
python agent.py history 1
python agent.py run 1 --steps 8
```

新規ジョブの成果物は `workspace/jobs/1/` のようなディレクトリに保存されます。`run` は指定ステップ数で止まり、ジョブはSQLiteに保存されます。

### URLを個別に許可

```powershell
python agent.py approve-url 1 "https://docs.python.org/3/library/ast.html"
python agent.py run 1 --steps 8
python agent.py revoke-url 1 "https://docs.python.org/3/library/ast.html"
```

URLはネットワークへ取得しに行くため、接続が必要です。モデルが `read_url` を選ぶかどうかは目標・判断内容によります。自動Web検索、リンク先の自動巡回、ロボットログインは未実装。URL先で更新があればその内容を取得します。追加の防御としてDNSのプライベート/予約済IPを検査しますが、**DNSリバインディング等まで完全に防げるネットワークサンドボックスではありません**。信頼できる公開サイトだけを承認してください。

### Gitスナップショットを許可

```powershell
python agent.py allow-git 1
python agent.py run 1 --steps 8
python agent.py deny-git 1
```

Gitがインストールされている必要があります。AIが `git_checkpoint` を選んだときだけコミットされます。自動的に必ずコミットするわけではありません。`.git` が既に存在する場合、当該リポジトリ内でコミットするので、実行前に作業フォルダを確認してください。生成物にパスワード・個人情報がないことを確認し、必要であればGitを許可しないでください。Gitのバックアップは同一PC内にあるため、PC故障対策にはなりません。

### テストを許可（危険性に注意）

```powershell
python agent.py allow-tests 1
python agent.py run 1 --steps 8
python agent.py deny-tests 1
```

**テストコードはWindowsユーザー権限で実行されます。OSサンドボックスはありません。** 書き込み可能なワークスペース内のコードがPC内の別ファイルにアクセスする危険性があります。信頼できる内容以外には使わないでください。テスト失敗が記録されればAIの次の判断に反映されますが、必ず修正できる保証はありません。

### Codexの明示的な手動起動（任意）

```powershell
python agent.py codex 1 --confirm
```

Codex CLIを別途インストールしてChatGPTアカウントでログイン。CodexはPlus利用枠を使い、`tick` による自動課金・自動消費は行いません。サンドボックスの実環境依存に注意。APIキー設定の場合は別途API料金が生じる可能性があります。

### 中断・自動再開

```powershell
python agent.py stop
python agent.py clear-stop
python agent.py unblock 1
.\install-schedule.ps1 -Minutes 30
```

Windowsのタスクスケジューラで、ログイン中に30分ごとに未完了ジョブを8ステップまで処理します。解除：

```powershell
Unregister-ScheduledTask -TaskName 'AutonomousAgentV06-LocalTick' -Confirm:$false
```

### ChatGPT通常チャットとの連携

```powershell
python agent.py chat-report 1
```

`chat-report-1.md` を作成。内容を確認し、手動で通常チャットに貼り付けて長期計画や失敗分析を依頼できます。API使用量を消費しないChatGPT通常チャットを自動的に叩く方法ではありません。

## v0.5からの移行

1. 旧タスクスケジューラを解除し、エージェントの起動を止める。
2. `state.sqlite3` と `workspace/` を**セットで**バックアップして新フォルダへコピーする。SQLiteのWAL/SHMが残らないよう、DB書き込み停止後にコピーする。
3. `python agent.py status` で状態確認。旧ジョブの作業領域割当は変更しない。
4. 必要ならv0.5のスケジュールを登録する。旧バージョンと重複登録しない。

## 検証

```powershell
python -m unittest discover -s tests -v
```

Linux/Python環境で40件の単体テストが成功。実機WindowsのOllama・Codex・タスクスケジューラや実サイトアクセスは未検証。外部Web検索、ブラウザ自動操作、自由なOS操作、任意リポジトリ全体の編集、本格的なサンドボックス・完全自動での自己修復は未実装です。


## v1.3: 完了判定の信頼性を改善

- `replace_in_file` でコードを変更した後は、以前のテスト合格だけを根拠に「完了」と判定しません。再テストが必要です。
- ジョブでテスト実行を明示的に許可した場合、Python成果物に `workspace/tests/test*.py` が一つもなければ完了を拒否し、AIにテスト作成を促します。
- GitHub上の既存コードとSQLiteデータの形式は維持しています。現在はP0-4の安全対策により、従来の「更新して起動.bat」は自動同期せずローカル版を起動します。
- テストを許可していないジョブには、従来どおりテストの自動実行を強制しません。テストが通っても成果物の正しさが保証されるわけではありません。


## v1.4 — 長期運用の信頼性を改善

### 1. 完了条件を明示する

目標を登録した後、**ファイルの存在・文字列の包含**を成功条件として追加できます。

```powershell
python agent.py new "Pythonの学習教材を作り、要点をまとめる"
python agent.py criteria 1 --file lesson.md --contains "lesson.md::要点"
python agent.py run 1 --steps 8
```

指定した成果物が存在しない、空である、または必須の文言を含まない場合は、AIが完了を宣言しても終了しません。成功条件が未設定なら従来のモデルによる完了評価を使います。条件はSQLiteに保存され、更新は上書き式です。特定ジョブのワークスペース内のみを参照します。

### 2. 行き詰まり時に再計画

直近の同一操作3回、または4回連続のエラーを検知すると、**最大2回だけ**代替計画を生成し、その後は従来どおり停止します。失敗履歴・成果物は保持します。モデル停止時など再計画できない場合はブロックします。回数はジョブを跨いで保持されます。

### 3. スケジュール実行の再試行待機

Ollamaの停止や予期しない例外で失敗したジョブは、次回のスケジュール実行を一定期間遅らせます（指数バックオフ、最大1時間）。待機情報はSQLiteに保存され、PC再起動後も有効です。手動の `run` は待機中でも実行できます。

これらは自律動作の安全性・成功を保証するものではありません。ジョブは上限300ステップ、定期実行は毎回指定したステップ数までです。OSレベルのサンドボックスは提供していません。Windows/Ollamaの統合試験は別途必要です。


## v1.5 — 自律エージェントの動作評価

GitHub Actionsの **Agent behavioral benchmark** がWindows・Linux（Python 3.11 / 3.13）で毎回実行されます。

```powershell
python benchmarks/run.py
```

以下の4シナリオを「本物のPython実行ループ・SQLite・ジョブ専用workspace」を使って検証します。

1. **study_note**: ノート作成・必須文字列の検証・完了
2. **python_with_tests**: モジュールとテストの生成・unittest実行・完了
3. **stall_recovery**: 同じ操作を3回した後、再計画して完了
4. **resume**: 作業回数で一時停止し、別のrun呼び出しで再開して完了

結果は `benchmark-results.json` に保存し、CIのArtifactsから取得できます。必ずジョブごとに隔離された一時フォルダでテストし、ユーザーの実作業データには触れません。

**重要:** モデルの回答と一部の最終評価は固定された模擬応答です。したがって、このベンチマークが4/4成功しても、Ollamaの実際の推論性能、検索品質、複雑なコード修正の成功率、数日間の連続運用を保証しません。次の段階で実機でのOllama統合評価と長時間運用のテストが必要です。

## v1.6 — GUI / ターミナル共通の操作と安全性監査

**GUI** には「成功条件を設定」「成功条件を見る」「PCへの影響・権限を確認」を追加しました。CLIと同じ `agent.py` のコマンドを呼び出すため、GUIとCLIでジョブ状態は共有されます。設定は `state.sqlite3` に保持されます。

```powershell
python gui.py                         # GUIを起動
python agent.py status                # CLIでジョブ一覧
python agent.py safety                # 全体の危険性と既定権限
python agent.py safety 1              # ジョブ1の実際の許可状態
python agent.py criteria-show 1       # 成功条件を表示（変更なし）
python agent.py criteria 1 --file lesson.md --contains "lesson.md::要点"
python agent.py run 1 --steps 8
```

### セキュリティ上の重要事項（コード監査）

- **Windowsの低レベル制御ではありません。** 通常のPythonアプリで、カーネル・ドライバーの直接制御やOS全体の汎用シェル操作ツールはありません。
- **デフォルトでテスト実行・Gitチェックポイント・Web検索は無効**です。Webページ本文へのアクセスはジョブごとにURLを承認した場合に限定されます。
- **重大な残余リスク:** `allow-tests` を許可すると、生成されたPythonテストが現在のWindowsユーザーの権限で実行されます。作業フォルダはOSレベルのサンドボックスではなく、他のファイルにアクセスし、外部通信や別プロセスの起動も可能です。未確認コードには許可しないでください。
- コードの書き込みは通常はジョブの作業フォルダに制限し、サイズ上限、シンボリックリンク検査、ファイルの簡易バックアップを設けています。ただしTOCTOU競合やハードリンクを含め、一般ユーザー権限の隔離を保証するものではありません。
- `allow-git` はローカルのチェックポイント作成を許可します。GitHubへの自動pushではありません。秘密情報をローカル履歴に記録する可能性があります。
- Web検索では検索語がBingに送信されます。承認した外部URLを読むと対象サイトへアクセスします。DNSリバインディング等に対する完全なネットワーク分離はありません。
- Windowsタスクスケジューラは `install-schedule.ps1` を**手動で実行した場合のみ**設定されます。スケジュール実行では、過去にテスト許可したジョブのテストも実行されうるため注意してください。
- 現時点ではWindows Sandboxまたは隔離VM内で試すことを推奨します。バックアップを取り、管理者権限では実行しないでください。


## v1.7 — 生成コードの隔離実行（重要な仕様変更）

**AIが作ったPythonテストをWindows本体で直接実行しない**ように変更しました。GUIとCLIの `allow-tests` は、Docker Linuxコンテナの準備が整っている場合に限り有効に働きます。Docker未導入・停止中・イメージなしの場合には**エラーを出して実行を拒否**します。通常実行への自動フォールバックはありません。

### Windowsでの初回準備

1. Docker Desktopを公式サイト（https://www.docker.com/products/docker-desktop/）からインストール。Linux containers / WSL 2バックエンドを利用し、起動する（Windowsのエディション・仮想化設定・RAMに応じて制約があります）。
2. PowerShellで一度だけ `docker pull python:3.11-slim` を実行。自動的にはイメージをダウンロードしません。
3. `python agent.py safety JOB_ID` から `sandbox.available` を確認。
4. GUIの「Pythonテスト実行を許可（注意）」、または `python agent.py allow-tests JOB_ID` でジョブごとの許可をオンにする。

### 主な制限

Dockerランナーは、作業フォルダから通常ファイルだけを使い捨ての一時領域へ複製し、生成されたテストを `--network none`、一時スナップショットの読み取り専用マウント、コンテナルートFSの `--read-only`、権限削除、非rootユーザー、CPU/メモリ/PID上限、45秒タイムアウトを使って実行します。コンテナはテスト終了後に削除され、タイムアウト時にも停止を試みます。ローカルDockerソケット/名前付きパイプのみを許可し、リモートDockerやWindowsコンテナは拒否します。

生成されたテストがワークスペースへ書き込むタイプの場合、読み取り専用制限により失敗します。テスト用の一時ファイルはコンテナ内 `/tmp` を利用する必要があります。生成コードはテスト実行中もコンテナの内部で実行され、ホスト作業フォルダへの書き込みは制限されます（Docker・OSの脆弱性がないことが前提）。一時スナップショットには200ファイル・合計10MBの上限があり、シンボリックリンクや隠しファイルは渡しません。

**隔離は絶対安全を意味しません。** DockerのLinuxコンテナ内からホストのファイルが完全に見えなくなるわけではなく、許可された一時スナップショットは読み取れます。 Docker Desktop/WSL2にはインストール・仮想化・メモリ・ディスク使用量が伴います。Docker自体の権限を渡したり、Dockerソケットをコンテナにマウントしたりしないこと。未信頼イメージを同じタグで使わないこと。重要ファイルのバックアップも必要です。

`python -m unittest discover -s tests -v` はプロジェクト自身の**信頼済み開発用テスト**であり、生成コードの隔離ルートではありません。実環境の隔離確認はGitHub Actions `Docker sandbox integration` で行います。


## v1.8 — Docker初期設定をGUIとCLIから案内

GUIに「**Docker環境を診断**」「**Pythonイメージを準備**」「**Docker公式サイト**」を追加しました。
診断とダウンロードはバックグラウンドの子プロセスで実行するため、Tkinterの操作スレッドを塞ぎません。

- **Docker環境を診断**：Docker CLI、Docker Desktop/Engine、コンテナモード、ローカル接続、必要なPythonイメージを調べ、次に必要な操作を日本語で案内します。診断だけではインストール・ダウンロード・設定変更を行いません。
- **Pythonイメージを準備**：ユーザーの確認後に限り、Docker Hubから固定の公式イメージ `python:3.11-slim` をダウンロードして確認します。Dockerのインストールや起動、Windows/WSLの設定変更は自動実行しません。
- **Docker公式サイト**：公式ダウンロードページを既定ブラウザで開きます。

### ターミナルでの同等操作

```powershell
python agent.py sandbox-status
python agent.py sandbox-prepare --confirm
python agent.py safety 1
```

`sandbox-prepare` では `--confirm` が必須です。Docker環境が利用できない場合はエラーで終了し、生成されたPythonテストをWindowsホストで直接実行することはありません。

**Windows環境での注意：** Docker Desktop/WSL2のインストールと有効化にはPC側の操作が必要です。今回のCIはWindows上でのGUIヘルパーとDocker診断ロジックの単体テスト、およびLinuxでの実Docker隔離テストです。ユーザー本人のWindows PCへのDockerインストールや実起動を遠隔実施したものではありません。

## v1.9 — 安全性優先の追加監査

安全性の詳細は [SECURITY.md](SECURITY.md) を参照してください。

今回の改善：
- ワークスペース書き込みのランダム・排他的な一時ファイル作成に変更。固定名の一時ファイルを悪用したリンク経由の意図しない書き込みを防ぐ。
- バックアップは排他的に生成。リンク化されたバックアップ先は拒否し、既存バックアップを勝手に上書きしない。
- Dockerコンテナへ渡す一時スナップショットから、隠しファイル、機密情報らしいファイル名、許可外の拡張子、ハードリンクを除外・拒否。**ソース中に直接書かれた秘密情報は検出できない**。
- Gitチェックポイントでは `.env` や `credentials.json` などの疑わしいファイル名を見つけたら拒否。ファイル本文中の秘密は検知できない。
- セキュリティ回帰テストを追加。危険な例に対して実際に拒否することを確認。

これらは**一部の具体的な脆弱性を低減する対策**であり、安全性の全面保証ではありません。特にエージェント本体・Codex CLI・WebアクセスはDocker内部に隔離されません。

## v2.0 — AI編集の人間レビュー・承認ゲート

新しいCLI/GUIジョブでは、AIが `write_file` または `replace_in_file` を提案した時点で**実際のファイルを書き換えず**、SQLiteに変更案を保存して `awaiting_approval` で停止します。変更はファイル差分を確認した人が承認した場合に限り反映されます。却下時は書き込みません。既存のジョブ・データは維持します。

**GUI:** ジョブを選択 →「変更案を確認・承認」→ 差分を確認 → 「承認して反映」または「却下する」。変更反映後に「開始 / 再開」で続きを実行します。v2.0への初回移行時、古いジョブにも承認制を自動適用します。「旧ジョブの保護を有効化」は、ライブラリから直接作成された未保護ジョブの補助用です。

**CLI:**
```powershell
python agent.py new "学習ノートを作る"
python agent.py run 1 --steps 8
python agent.py pending 1
python agent.py change-preview 1 CHANGE_ID
python agent.py approve-change 1 CHANGE_ID
# または python agent.py reject-change 1 CHANGE_ID
python agent.py run 1 --steps 8

# 未保護と表示されるジョブにも承認ゲートを適用
python agent.py protect-job OLD_JOB_ID
python agent.py safety OLD_JOB_ID
```

新規CLI/GUIジョブの承認制は有効で始まります。旧バージョンからのジョブは初回DB移行で自動的に承認制へ変更します。直接Python APIで`make_job(goal)`した未保護ジョブについては、`protect-job`で明示的に保護してください。いったん保護したジョブをCLIから無効化する機能は提供しません。

**重要な安全上の区別:** これはAIによる「ファイル編集の提案」と「ホストへの変更の反映」を切り分ける承認方式であり、**エージェント本体をDocker内に移してはいません**。AIのPythonテスト実行は従来のDocker隔離を維持します。保護ジョブでは、承認ゲートを迂回するCodexの直接実行とAIのGitチェックポイント作成を禁止しています。作業フォルダへのホスト側の書き込みは承認時のみ発生します。ユーザー自身が編集する場合は通常のWindowsファイル操作として動作します。

変更提案後にファイル内容が変化すると承認は拒否されます。一般ユーザー権限の同一PC上で悪意ある別プロセスが動く場合の全競合を防ぐものではありません。OS全体のアクセス権制御、シェル操作、Codexを包括的に隔離する機能はまだありません。

## v2.1 — 承認前の検査・差分一括レビュー・復元

新規・既存の承認制ジョブでは、明示的に承認したファイル変更の**直前のバイト列をSQLite内に保存**します。GUIの「変更を元に戻す」から対象IDを選び、承認後とファイル内容が同じ場合に限って、元の内容へ戻せます。新規作成ファイルの場合は削除して元の「存在しない」状態へ戻します。

GUIの「変更案を確認・承認」は、複数の保留案がある場合は全件の差分をまとめて表示できます。CLI:
```powershell
python agent.py pending 1
python agent.py batch-preview 1 12 13
python agent.py approve-batch 1 12 13
python agent.py snapshots 1
python agent.py rollback 1 SNAPSHOT_ID
```

一括承認は最大20件、同じパスへの重複変更を拒否し、**適用前に全変更が古くなっていないか・明らかな秘密情報らしいパターンがないか検証**します。通常の途中エラーでは適用済みの変更を戻す処理を試みます。ただし**停電・強制終了・ファイルシステム障害まで含めた完全なトランザクションではありません**。この場合は`snapshots`と`rollback`を使って状態を確認してください。

秘密情報の検出は秘密鍵ヘッダー、一部のGitHub/AWSキー形式、一定の代入表現を対象にする限定的な検査です。漏れも誤判定もあります。これだけで秘密情報の漏えいを防げるとは考えないでください。

**制限:** 現在のAIループは1ファイルの提案ごとに承認待ちとなります。AIが複数ファイルを自律的に編集し、その後に一括承認する仕組みは、今後の隔離ワークスペース版で対応予定です。v2.1の一括承認は、複数の保留変更案がすでに存在する場合に利用できます。スナップショットと承認案はローカルSQLiteに保存されるため、コードや秘密を含む場合もあり、DBファイルを第三者へ共有しないでください。

## v2.2 — SQLite仮想ワークスペースで複数ファイルを自律編集

新規GUI/CLIジョブは**一括下書きモード**で開始します。従来は1回の `write_file` で停止していたところ、v2.2では最大20ファイルの編集案をSQLiteに保管したまま、AIが `write_file`、`replace_in_file`、`read_file`、`list_files`、`check_python` を繰り返せるようにしました。同じファイルへの複数編集は1件の最新案に集約します。目標の完了をAIが申し出たときにファイル構文と成功条件を確認し、テストを明示的に許可したジョブでは**Docker隔離テスト**を実行してから人間の一括レビュー待ちにします。

**安全上の境界：** 編集案はSQLiteの仮想オーバーレイであり、AIが直接ホストの成果物を編集する仕組みではありません。テストでは実行用に使い捨てファイルを作り、既存のDocker Linuxコンテナで実行します（ネットワーク遮断、読み取り専用）。**AIによるファイル編集処理そのものをDocker内で動かしているわけではありません。** Ollamaの計画と推論もホスト上です。最終成果物を専用作業フォルダに反映するには、GUIの差分確認・一括承認が必要です。バッチ反映はv2.1と同じく停電時の完全な原子的更新を保証しません。

### 操作

- 新規ジョブ：GUIから「目標を登録」→「開始 / 再開」で仮想下書きを作成します。AIが完了を申し出たら「変更案を確認・承認」を押し、すべての差分を確認したうえで承認します。
- 以前のジョブ：GUIの「既存ジョブを一括下書きモードにする」を押して有効にできます（未承認の変更がある場合は先に処理してください）。

```powershell
python agent.py new "Pythonとテストを書く"
python agent.py run 1 --steps 15
python agent.py pending 1
python agent.py batch-preview 1 CHANGE_ID1 CHANGE_ID2
python agent.py approve-batch 1 CHANGE_ID1 CHANGE_ID2
# 既存ジョブは手動で一括下書きを有効化
python agent.py enable-draft OLD_JOB_ID
```

**既知の制限：** 変更案の検査・テストに失敗した場合、AIへエラーログを渡して修正を促しますが、実際の正解を保証しません。プレビュー/レビューにはモデルの自己評価が含まれない部分があります。1件ごとに承認する従来モードも既存ジョブでは引き続き利用できます。保護ジョブではGitチェックポイントやCodexの直接実行は禁止されたままです。

## v2.3 — 実Ollamaによる性能評価（ローカル実行）

v1.5の模擬AIシナリオとは別に、**実際のローカルOllamaモデルに計画・判断させる**ベンチマークを追加しました。通常のジョブDBには接続せず、ケースごとに使い捨てのSQLite/ワークスペースを生成します。**生成されたファイルは自動承認しません。AI生成Pythonコードは実行しません。Web検索・Git・Codex・Pythonテストの権限は全て無効**です。

WindowsでOllama起動済み、`ollama pull gemma3:4b`実施済みの状態で、プロジェクトのフォルダから:

```powershell
python benchmarks/real_ollama.py --model gemma3:4b --steps 14 --trials 2 --output benchmark-results/gemma3-v23.json
```

実際のモデルの動作を3タスク（Markdown教材・厳密なJSONファイル・Python関数の定義）で採点し、ステップ数、所要秒数、再計画回数、エラーイベント、失敗分類、モデルダイジェストをJSONに保存します。繰り返し回数やシナリオを限定できます:

```powershell
python benchmarks/real_ollama.py --scenarios note,json --trials 1 --steps 10
```

別モデルとの結果比較:

```powershell
python benchmarks/compare_ollama.py benchmark-results/before.json benchmark-results/after.json --output benchmark-results/comparison.json
```

**評価の注意点:** Pythonシナリオは関数名・引数・構文と副作用の少ないコード構造を**静的に検査するのみ**で、計算結果の正しさを証明しません。教材の内容品質や文章の正確さも完全には採点できません。ベンチマークの`passed`は実用的な信頼性や安全性を保証しません。同じモデルでも推論時の確率性、PC負荷、プロンプト変更で結果が変わります。比較は同じシナリオ・ステップ数・試行回数を使ってください。

**GUIから実行:** 「実AIの性能を評価（Ollama）」ボタンでモデル名・試行回数・ステップ数を選べます。実測完了後は `benchmark-results/real-ollama.json` に記録されます。**課題の不正解も測定データとして正常終了**し、結果JSONの `passed` と `failure_category` を確認してください。Ollama接続失敗はエラー扱いです。

**テストと実測の区別:** GitHub Actionsはコードの動作を模擬した回帰テストと隔離テストのみ実施します。GitHub Actionsで`gemma3:4b`の推論実測を行ったわけではなく、実測はOllamaがインストールされたPCで実行して初めて結果が出ます。

## v2.4 — 評価結果から失敗原因を整理して改善案を作成

v2.3で保存した**実Ollamaベンチマーク結果**をオフラインで分析し、根拠のある改善候補と検証方法を作成します。モデルに追加問い合わせする機能ではありません。実測がない状態で改善案を作ったり、コード・プロンプト・設定を自動的に変更したりしません。

### GUI

1. 「実AIの性能を評価（Ollama）」で実測値を保存する。
2. 「評価結果から改善案を作成」を押す。
3. `benchmark-results/diagnosis.md` を開き、根拠と検証方法を人間が確認する。

### CLI

```powershell
python agent.py benchmark-diagnose
python benchmarks/diagnose_ollama.py --input benchmark-results/real-ollama.json --output benchmark-results/diagnosis.json --markdown benchmark-results/diagnosis.md
```

分析では、ホストへの意図しない書き込み、Ollamaや実行環境のエラー、停止、生成物の不一致、検証失敗、ステップ不足などを分類します。件数・対象シナリオ・失敗した検査項目を記録し、重要度順に改善案を提示します。成功時には無理に改善課題を作りません。

**安全性と限界:** 分析には保存済みJSONしか使いません。生成コード実行、ネットワーク送信、ジョブ操作、プログラムの自動更新はありません。出力先は指定した診断ファイルだけです。分析が提示するのは原因の確定ではなく**観測に基づく仮説**であり、人間が変更内容を確認して、同条件の実測で効果を判断する必要があります。

## v2.5 — 人間が承認する改善仮説の比較実験

v2.4の失敗分析を参考に、人間が選んでテキストファイルに書いた追加指示を、実Ollamaで比較できるようにしました。候補の指示は実験中の「次の行動を判断するプロンプト」にだけ加えます。計画生成・採点基準・本番ソースコードは変更しません。ベースラインと候補に同じモデル・課題・最大ステップ・試行回数を適用します。

### 使い方

まず v2.4 の診断結果を確認し、試したい改善仮説を自分で `experiment-note.txt` にUTF-8で書いてください（4000バイト以内）。例：`Before finish, verify every required field and the target filename.`

```powershell
python agent.py benchmark-experiment --instruction-file experiment-note.txt --confirm --model gemma3:4b --steps 14 --trials 2
```

GUIには「改善案を比較実験」を追加しました。人間が追加指示ファイル・モデル・試行回数・ステップ上限を指定し、実行前に明示的に承認します。

結果は `benchmark-results/experiments/` の固有フォルダに `baseline.json`、`candidate.json`、`comparison.json` を保存します。既存結果は上書きしません。改善候補を自動採用して本番エージェントのコードやプロンプトを書き換える機能はありません。

**限界:** 実Ollamaによる成功率は、ローカルPCで実行して初めて測定できます。GitHub ActionsのCI成功はモデル能力の向上を意味しません。試行回数が少ない場合の成功率差は偶然であり得ます。Python課題は構文や関数定義の静的評価のみです。

**安全性:** `--confirm` がなければ実行しません。ローカルOllamaのみを呼び出し、使い捨てDBと仮想ワークスペースを使用します。生成コード実行、Web検索、Git、Codex、自動承認は許可しません。追加指示は最大4000バイトで、AI生成の診断文書を無条件に自動適用しません。

## v2.6 — PC・機密情報・ネットワークの安全性強化

v2.6は新機能よりも**安全境界の強化**を優先した更新です。既存の仮想下書き、一括承認、Docker隔離テスト、Ollama・GUI・CLIを維持しています。

- **WebのDNSすり替え対策:** 承認したHTTPSページ取得と、許可された検索の両方で、DNS応答のIPアドレスが公開アドレスか検査します。その**検査済みIPをTCP接続先として固定**します。TLSの証明書検証には元のドメイン名を用い、リダイレクトとプロキシを使いません。Webアクセスは引き続きジョブごとの許可制です。
- **Ollama通信:** モデル呼び出しとベンチマークのモデル確認は、ローカルHTTP `/api/chat` への接続に限定します。プロキシとHTTPリダイレクトを無効化し、`localhost` は安全なループバック確認後に `127.0.0.1` へ固定します。リモートAPIへ目標・履歴を送信しません。
- **機密ファイル・Windows特殊パスの拒否:** AI操作の対象から隠しファイル、`.git` 配下、秘密情報を示すファイル名、Windowsの予約デバイス名、末尾に空白/ピリオドがある名前を除外します。ハードリンクされた既存ファイルもAIの読み取り・検索・変更対象から拒否します。これらの名前で作業したい場合はユーザー自身が安全性を確認して別のツールで扱ってください。
- **回帰テスト:** ローカルのDNSすり替え、プライベートIPへの接続、HTTPリダイレクト、リモートOllama設定、隠し認証情報、ハードリンクの取り扱いをテストに追加しました。

**残るリスク:** エージェント本体はWindowsの通常ユーザー権限で動いており、完全なOS分離はありません。Dockerの安全性、Windowsの特殊ファイル機能・権限や他プロセスとの競合、ソースコード本文に埋め込まれた認証情報、明示的に許可した外部送信、ユーザーが承認した危険な内容は完全には防げません。重要なファイルは独立した場所にもバックアップしてください。

**Git操作の追加制限:** v2.6では `git_status` もGit操作の明示的な許可が必要です。新規・保護された仮想下書きジョブでは、Gitの状態確認とチェックポイント作成の両方を禁止しています。Gitが利用可能な旧ジョブでも `core.fsmonitor=false` などの安全設定を強制します。Git設定のあらゆる外部実行経路が完全に消えるわけではありません。

## P0-4 段階1 — 未検証mainの自動適用を停止

**正式運用用の更新機能はまだ完成していません。** 現行の既定ランチャーはローカル版のみ起動し、GitHubのmainを勝手に実行しません。更新がない状態でも、既存のデータやジョブはそのままです。

使用するバッチファイル:

- `安全に起動.bat`: ローカル版を安全起動（ネットワークで新しいコードを取得しない）
- `更新して起動.bat`: 以前のショートカット互換。現在はローカル版を起動するだけ
- `開発版を更新して起動.bat`: 実験版のmain更新を**明示的に許可**してから起動。これ自体は検証済みReleaseではないため通常運用には推奨しません

署名付きGitタグの事前検査のみ行う仕組みも追加しています。**署名検査が成功しても自動インストールはしません。** 信頼するGPG署名鍵のフィンガープリントは、GitHubのリポジトリに含まれる文書を盲目的に信用せず、独立に確認してから、Windowsでは `%LOCALAPPDATA%/AutonomousAgent/release-trust.json` に保存する設計です。ファイル形式例（`<PINNED_FINGERPRINT>`は実在し、独立に検証した署名者の指紋へ置き換える）:

```json
{"repository":"ryotkkr-del/Autonomous-Agent","trusted_fingerprints":["<PINNED_FINGERPRINT>"]}
```

Gitへのタグ取得を伴う検証専用コマンド:

```powershell
powershell -NoProfile -File .\sync.ps1 -CheckReleaseTag v3.0.0
```

タグの署名と独立した信頼設定が合致しない限り拒否します。現時点では実際に署名済みのRelease配布物を確認していないため、**安全なRelease自動インストール・CI合格照合・旧版への復旧は未実装**です。これらがP0-4段階2の残課題です。

## P0-4 段階2 — 更新前のバックアップ・検証・非破壊的な復旧コピー

開発版mainの更新（`開発版を更新して起動.bat`）では、警告と `DEV-UPDATE` の入力に加え、**Git fetch/merge の前に** `safety_backup.py` によるバックアップ作成・整合性検証を必須化しました。失敗時は更新を中止します。普段の `安全に起動.bat` と `更新して起動.bat` はローカル起動のみです。

バックアップ対象は、存在する `state.sqlite3`、`workspace/`、`benchmark-results/` です。SQLiteはWALファイルの直接コピーではなく、SQLiteのオンラインバックアップAPIで独立したDBファイルへ複製し、`PRAGMA integrity_check` を行います。ファイルごとのSHA-256も記録します。旧バックアップは自動削除しません。

保存先はWindowsで `%LOCALAPPDATA%\AutonomousAgent\backups\snapshot-...`、Linuxで `~/.local/share/AutonomousAgent/backups/snapshot-...` です。**インストール先の外側**に保存されます。

### 手動で作成・確認（実行中のジョブを停止してから）

```powershell
python -I safety_backup.py create
python -I safety_backup.py verify --snapshot "$env:LOCALAPPDATA\AutonomousAgent\backups\snapshot-YYYYMMDDTHHMMSSZ-xxxxxxxxxxxx"
```

### 復元する場合（必ず新しい別フォルダへ）

```powershell
python -I safety_backup.py recover --snapshot "$env:LOCALAPPDATA\AutonomousAgent\backups\snapshot-YYYYMMDDTHHMMSSZ-xxxxxxxxxxxx" --into "$env:USERPROFILE\AutonomousAgent-Recovered"
```

`recover` は**元のSQLiteや作業フォルダを上書きしません**。復旧コピーを確認するための操作です。アクティブデータへ戻す安全な切替・自動復旧はまだ未実装です。

### 限界・注意

- 1ファイル100MiB、総量500MiB、最大5000ファイル。超過時は一部を省略せず失敗させ、更新を拒否します。
- シンボリックリンク・Windows reparse point・ハードリンクを含むファイルは拒否します。
- SQLiteと別プロセスが編集するワークスペース全体の厳密な同一時点でのスナップショットは保証していません。実行中のタスク・GUI・スケジュールによる編集を停止してください。
- SHA-256照合は偶発的な破損の検出であり、バックアップフォルダを改ざんできる相手に対する署名ではありません。
- バックアップにはコード・ジョブの内容・個人情報や秘密が含まれ得ます。共有せず、個人用の安全な保存先に置いてください。
- **P0-4はまだ部分達成**。実際の署名付きReleaseの配布・CI合格確認・配布物の真正性・コードの原子的切替・失敗時の自動ロールバック・Windows 11実機での総合確認は残っています。

## P0-4 段階3 — 署名・CI成功・Gitオブジェクトの照合と候補の安全な準備

新しい `release_candidate.py` は、独立して設定したGPG署名者のフィンガープリントに一致する署名済みGitタグを検証し、そのタグが示すコミットについて、GitHub Actionsの**3つの必須ワークフロー**が全て `main` への `push` で成功しているか確認します。

必須ワークフローは `.github/workflows/tests.yml`（Windows・LinuxのPython単体テスト）、`.github/workflows/benchmark.yml`（模擬エージェント評価）、`.github/workflows/sandbox-integration.yml`（実Docker隔離テスト）です。別コミット、PRイベント、実行中、失敗した結果は認めません。CIの判定はGitHub APIに依存し、独立した暗号学的ビルド証明ではありません。

署名済みReleaseタグの取得（前回の確認機能）:

```powershell
powershell -NoProfile -File .\sync.ps1 -CheckReleaseTag v3.0.0
```

**検査だけ実施**（ソースを展開しない）:

```powershell
python -I release_candidate.py --tag v3.0.0
```

**人間が指定した場合だけ候補コードを別領域に準備**（自動実行・切替はなし）:

```powershell
python -I release_candidate.py --tag v3.0.0 --stage
```

保存先はWindowsでは `%LOCALAPPDATA%\AutonomousAgent\release-candidates\candidate-...`、Linuxでは `~/.local/share/AutonomousAgent/release-candidates/candidate-...` です。`app/` は検証済みソースのコピー、`release-metadata.json` はコミット・署名者指紋・CI実行ID・ファイルSHA-256の記録です。

候補はGitのタグが指すコミットからファイルオブジェクトを読み出し、オブジェクトIDを照合してから保存します。Windowsの改行変換を避けるため、`git checkout` や圧縮アーカイブの自動展開は行いません。不正パス、リンク、Windows特殊ファイル名、巨大なファイル、内容の不一致は拒否します。

**重要:** 現時点のGitHubには正式なReleaseが登録されていません。信頼済み署名タグと独立した鍵の設定がなければこの機能は失敗して停止します。CLIはGitHub上の署名済みReleaseの発行、インストール、コードの切替、旧コードへのロールバック、SQLiteの復旧を行いません。`開発版を更新して起動.bat` は引き続き別の未検証main用の開発者操作であり、正式運用を意味しません。
