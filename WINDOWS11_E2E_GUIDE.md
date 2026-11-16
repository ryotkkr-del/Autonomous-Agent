# Windows 11 実機スモークテスト（記録用）

> **この文書は試験手順です。実施済みの報告ではありません。** GitHub-hosted Windows CIとWindows 11の利用者PCは異なります。開発ブランチで実験する場合は標準ユーザーまたは隔離VM、ダミーデータを利用してください。

## 0. 対象コード

以下の追加診断はPR #1の開発ブランチにあり、未統合の `main` にはありません。正式Releaseの署名やインストールの安全性を意味しません。既存のインストールを上書きせず、必ず新規フォルダへ取得してください。

```powershell
git clone https://github.com/ryotkkr-del/Autonomous-Agent.git
cd Autonomous-Agent
git switch --track origin/hardening/p0-4-candidate-preflight-20261116
```

## 1. 自動診断（読み取り専用の操作だけ）

```powershell
python -I trial_readiness.py --json
python -I windows_runtime_probe.py --probe-runtime --json
```

`trial_readiness.py` はPython・Tkinterと必要なローカルファイルの存在を確認。`windows_runtime_probe.py` は**明示的にフラグを指定した場合のみ**、ローカルOllamaの `/api/tags` へGETし、DockerのローカルLinuxエンジン・既存Pythonイメージを状態照会します。モデルへの推論リクエスト、モデルpull、Dockerコンテナの起動・pull、アプリ起動、ローカルDBの読み取り/変更は行いません。ユーザーのフォルダ名、環境変数、モデル一覧、Dockerの生ログを診断結果に含めません。

`runtime_prerequisites_found_not_e2e` と表示されても**実機E2E成功ではありません**。Ollamaのモデルがリストに表示されたこと、Dockerの準備が確認できたことまでです。エラーを直すためのシステム設定変更やソフトのインストールは自動実行しません。

## 2. GUI・AI推論の人手確認（ここからはアプリがデータを作成します）

この段階はテスト用の新規フォルダのみで実行してください。事前に停止中の別エージェントや旧タスクスケジューラがないことを確認し、**管理者として実行しない**でください。

1. `python gui.py`でGUIが表示でき、ウィンドウの終了操作に問題がないか目視で確認する。
2. 「接続・環境を確認」でOllamaの接続・モデル設定が通るか確認する。`/api/tags`の診断成功だけでは実際の推論成功は証明されない。
3. Web検索・URL参照・Git・Codex・テスト実行を許可せず、ダミー目標を1件作成し、少数ステップだけ開始する。計画・イベント履歴がGUIに記録されるか確認する。
4. 停止操作を行い、処理が止まったことをGUIとCLIの両方で確認する。GUIを閉じた後も子プロセスが残る可能性があるため終了を目視確認する。
5. GUIを再起動し、同じジョブと履歴が残っていることを確認する。ただし、STOPが残っている場合は意図的に解除するまで実行されない。
6. **GUIを閉じる際の保護:** ダミータスクを実行中にウィンドウの×を押し、終了確認ダイアログが表示されることを確認する。キャンセルした場合はSTOPが勝手に作られないこと、終了に同意した場合はSTOP作成後も子プロセスの終了前にウィンドウが消えないこと、子プロセス終了後にGUIが閉じることを確認する。STOPは処理ステップ境界で確認するため、現在の操作完了まで時間がかかる場合がある。**強制終了は行わない**。

## 3. Docker隔離の実測（未自動実施）

Docker診断成功は`docker run`で実際に生成Pythonテストを隔離できる証明ではありません。Docker Desktop/WSL2の準備ができた後、**テスト用VM等で**、ネットワーク接続・ホストへの書き込み・コンテナからの権限昇格の否定試験、資源上限、キャンセル時のコンテナ終了を別途計測してください。仕事用PCで未知のテストコードを実行して確認しないでください。

## 4. 結果記録（パスやユーザー名を書かない）

| 項目 | 記入例 |
|---|---|
| OSの種類 | Windows 11 / Windows Server CI / 未確認 |
| Python/Tkinter | pass / fail / not-run |
| Ollama状態照会 | pass / fail / not-run |
| gemma3:4bの存在 | pass / fail / not-run |
| Docker Linux環境とイメージ | pass / fail / not-run |
| GUI表示・終了 | pass / fail / not-run |
| ダミー目標と実モデルの出力 | pass / fail / not-run |
| 停止・再開 | pass / fail / not-run |
| 実行中にGUIを閉じた場合の子プロセス待機 | pass / fail / not-run |
| SQLiteと履歴の保持 | pass / fail / not-run |
| Docker隔離否定試験 | pass / fail / not-run |
| 安全なRelease更新と復旧 | **not-implemented** |

**合格判定:** このチェックリストを実際のWindows 11標準ユーザーで実施し、Ollama/GUI/停止・保存/必要ならDockerを確認して初めて当該機能の実機確認と記録できる。全P0や正式運用の合格判定は別であり、署名付きRelease、実際の更新切替・復帰、電源断耐性、悪意ある入力への包括的検証が必要。
