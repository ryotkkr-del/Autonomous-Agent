# Autonomous Agent v1.2

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

以後は **`更新して起動.bat`** をダブルクリックすると、GitHubの`main`をfast-forwardで取り込み、GUIを起動します。既存の作業ファイルはGitで自動上書きしません。PCがオフの間は動きません。

すでにGitHubからcloneしている人は、既存のフォルダから`更新して起動.bat`で更新してください。初回用の`GitHubへアップロード.ps1`や`初回セットアップ.bat`は**現在不要**です（旧版の説明が残っている場合は使わないでください）。

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

本体は無料ローカル推論を利用します。Codexは明示的な許可による手動実行のみで、ChatGPT Plus利用枠の対象です。PythonテストはOSレベルのサンドボックスではなく、ユーザー権限で動くため信頼済みコードに限って許可してください。Windows実機でのOllama・Codex連携は未検証。Linux上で64件の単体テストが成功しています。

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
