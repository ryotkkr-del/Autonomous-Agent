# Autonomous Agent — Windows 11 初回試用ガイド

> **正式運用向けではありません。** 現在は署名付き公式Releaseがなく、Windows 11 + 実Ollama + Docker Desktopの統合試験も未完了です。通常ユーザー権限か隔離VMで、ダミーデータだけを使用してください。

## 試用するコードを選ぶ

- **一般の試用:** 公開中の `main` ブランチを新しいフォルダへclone。GUIと基本タスクを試せます。新しい `trial_readiness.py` はまだ `main` にはありません。
- **安全機構の開発版の評価:** Draft PR #1のブランチを別フォルダで選択。CIは通っていても、未レビューの開発コードであり本番利用はできません。

## 初回手順

1. 既存アプリのフォルダを上書きしない。管理者で起動しない。重要データ、秘密鍵、認証情報をworkspaceへ入れない。可能なら別のWindows標準ユーザーまたはVMを使用。
2. 公式配布元のPython 3.11以降、Git for Windows、Ollamaを準備する。モデルがまだなければ、`ollama pull gemma3:4b` を手動実行（初回のみ通信・ディスク容量が必要）。
3. **新しい空のテスト専用フォルダ**で以下を実行。GitHub上の開発用ソースは署名付き正式配布物ではない。

```powershell
git clone https://github.com/ryotkkr-del/Autonomous-Agent.git
cd Autonomous-Agent
```

4. `main` の試用では `python agent.py doctor` で状態を確認し、`安全に起動.bat` または `python gui.py` でGUIを起動。
5. Draft PRの事前チェックを使う場合に限り、GUI起動前に次を実行（未統合コードのため開発者向け）。

```powershell
git switch --track origin/hardening/p0-4-candidate-preflight-20261116
python -I trial_readiness.py
python -I windows_runtime_probe.py --probe-runtime --json
```

`trial_readiness.py` は読み取り専用・オフラインの静的チェックです。`manual_trial_prerequisites_found` はファイルと基本環境を確認しただけで、安全性・Ollama接続・Docker稼働・署名を保証しません。`not_ready`なら原因を解消するまで起動しないでください。

6. GUIではダミーのジョブを1件だけ、少数ステップで実行。Web検索、外部URL、Git、Codex、Pythonテストの許可を有効化しない。ファイル差分の承認も実運用データには行わない。
7. 終了時はジョブ停止を確認してGUIを閉じ、エージェントの処理が継続していないか確認する。STOPを作った場合、再開には意図的な解除が必要。

Windows 11実機でGUI起動・停止・Ollama推論まで検証する具体的な手順と記録表は [WINDOWS11_E2E_GUIDE.md](WINDOWS11_E2E_GUIDE.md) を参照してください。`--probe-runtime` はローカルOllama/Dockerの状態照会だけで、アプリ起動や生成コード実行は行いません。

## 試用中は使わない

- `開発版を更新して起動.bat`（署名付き正式Releaseへの更新ではなく、mainへの開発版追従）
- `install-schedule.ps1`（無人定期実行）、外部Codex/CLI、長時間の無人実行
- 本番の個人・業務データ、管理者権限、重要フォルダへのアクセスを要するタスク

## 安全性の境界

既定の `安全に起動.bat` はmainを自動取得しません。生成コードの実行テストはDocker環境が必要で、利用できなければ拒否する設計です。一方でエージェント本体、GUI、Ollama、Git/Codex全体はOSレベルで隔離されません。

GitHub CI合格、静的診断成功、バックアップ作成成功のいずれもWindows 11実機や実データの安全性を証明しません。残課題は [ROADMAP_PROGRESS.md](ROADMAP_PROGRESS.md) と [SECURITY.md](SECURITY.md) に記載しています。
