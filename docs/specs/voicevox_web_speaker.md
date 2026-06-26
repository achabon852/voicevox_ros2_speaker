# 要件定義書: VOICEVOX WEB 発話システム

## 目的

ROS2 Jazzy 上で動作するロボットの発話機能を、ブラウザ上のフォームから手軽に操作できるようにする。
研究室・デモ展示での動作確認・デモを主目的とし、VOICEVOX Engine（Docker）を音声合成バックエンドとして利用する。

## 非ゴール（やらないこと）

- ロボット外部のリモートホストへの VOICEVOX 接続（localhost 固定を想定）
- 認証・アクセス制限（LAN 内デモ用途のため不要）
- ブラウザでの音声再生（PC スピーカー直接再生のみ）
- 発話内容の永続的なログ保存・履歴表示
- マルチロボット対応

---

## システム構成

```
[ブラウザ]
   │  HTTP（静的ファイル取得）
   │  WebSocket（rosbridge, port 9090）
   ▼
[ROS2 ノード群（同一 PC）]
   ├─ rosbridge_server（ws://localhost:9090）
   │     ↕ pub/sub
   ├─ speaker_node
   │     │  GET http://localhost:50021/...
   │     ▼
   │  [VOICEVOX Engine（Docker, localhost:50021）]
   │     → WAV データ取得
   │     → PCスピーカーで再生（sounddevice）
   └─ /voicevox/speak  topic（std_msgs/String, JSON）
      /voicevox/status topic（std_msgs/String, JSON）
```

### ROS2 トピック設計

| トピック名 | 型 | 方向 | ペイロード例 |
|-----------|-----|------|------|
| `/voicevox/speak` | `std_msgs/String` | Web → Node | `{"text":"こんにちは", "speaker_id":2, "speed":1.0, "volume":1.0}` |
| `/voicevox/status` | `std_msgs/String` | Node → Web | `{"state":"speaking", "message":"発話中"}` |

`state` の値: `idle` / `speaking` / `error`

---

## 機能要件

**F-01 テキスト入力と発話パラメータの設定**
- ユーザーが Web フォームにテキストを入力し、話者・速度・音量を選択して「発話」ボタンを押したとき、システムは `/voicevox/speak` トピックに JSON 文字列を rosbridge 経由でパブリッシュする。

**F-02 音声合成（VOICEVOX API 呼び出し）**
- `speaker_node` が `/voicevox/speak` を受信したとき、システムは VOICEVOX Engine の `/audio_query` → `/synthesis` API を順に呼び出して WAV データを生成する。

**F-03 PC スピーカー再生**
- WAV データが生成されたとき、システムは `sounddevice` を用いてデフォルトの PC オーディオデバイスで再生する。

**F-04 発話キュー管理**
- 発話中に新しい `/voicevox/speak` メッセージを受信したとき、システムはそのリクエストをキューに追加し、現在の発話完了後に順次処理する。
- キューの最大長は 10 件とし、超過した場合は最も古いリクエストを破棄してから追加する。

**F-05 VOICEVOX 接続エラー処理**
- VOICEVOX API 呼び出しが失敗したとき、システムは 1 秒間隔で最大 3 回リトライする。
- 3 回すべて失敗したとき、システムは `/voicevox/status` に `{"state":"error","message":"VOICEVOX に接続できませんでした"}` をパブリッシュし、Web UI にエラーメッセージを表示する。キューはクリアする。

**F-06 ステータス表示**
- `speaker_node` が発話を開始・完了・エラー終了したとき、システムは `/voicevox/status` トピックにその状態を通知し、Web UI がリアルタイムに表示する。

**F-07 話者一覧の動的取得**
- Web ページ読み込み時、システムは VOICEVOX Engine の `/speakers` エンドポイントから話者一覧を取得し、セレクトボックスに表示する。
- 取得失敗時はデフォルト話者（四国めたん / ID:2）を使用し、その旨をUIに表示する。

---

## 受け入れ基準

- [ ] ブラウザから `http://localhost:<port>` を開いたとき、フォームが表示される
- [ ] 話者セレクトボックスに VOICEVOX の話者一覧が表示される
- [ ] テキストを入力して「発話」ボタンを押すと、PC スピーカーから音声が再生される
- [ ] 速度スライダーを最小・最大にして発話したとき、それぞれ遅い・速い音声になる
- [ ] 音量スライダーを 0 にしたとき、無音で再生が完了する
- [ ] 発話中に「発話」ボタンを押すと、2 件目はキューに積まれ 1 件目完了後に再生される
- [ ] キューが 10 件を超えたとき、最も古いリクエストが破棄される
- [ ] VOICEVOX コンテナを停止した状態で発話すると、3 回リトライ後に UI にエラーが表示される
- [ ] ステータス（発話中 / 待機中 / エラー）が UI にリアルタイムで表示される
- [ ] `ros2 topic echo /voicevox/speak` で発話リクエストの JSON が確認できる

---

## 変更が必要なファイル一覧

新規作成（既存ファイルなし）:

```
src/
  voicevox_speaker/
    voicevox_speaker/
      __init__.py
      speaker_node.py        # ROS2ノード（キュー管理・VOICEVOX API呼び出し・再生）
    web/
      index.html             # Web UI（rosbridge WebSocket 接続）
    package.xml
    setup.py
    setup.cfg
    resource/
      voicevox_speaker
    launch/
      voicevox_speaker.launch.py
docker-compose.yml           # VOICEVOX Engine コンテナ定義
docs/
  specs/
    voicevox_web_speaker.md  # 本ドキュメント
```

---

## リスク・前提

### 前提

- ROS2 Jazzy Jalisco インストール済み
- Docker / docker-compose インストール済み
- VOICEVOX Engine Docker イメージ: `voicevox/voicevox_engine:cpu-ubuntu20.04-latest`（GPU なし版）
- Python 3.10+（ROS2 Jazzy の標準）

### リスク

| リスク | 対策 |
|--------|------|
| rosbridge パッケージが未インストール | `ros-jazzy-rosbridge-suite` を apt でインストール |
| sounddevice がオーディオデバイスを認識しない | `python3-sounddevice` + `libportaudio2` の確認、環境変数 `PULSE_SERVER` の設定 |
| VOICEVOX Docker イメージが大きい（約 3GB） | 初回 `docker compose pull` に時間がかかる旨を README に記載 |
| 話者 ID が環境依存 | 起動時に `/speakers` で動的取得し、ID をハードコードしない |
| キューが無制限に肥大化 | 最大キューサイズ 10 件を設け、超過時は古いものを破棄 |

---

## 検証手順

```bash
# 1. VOICEVOX 起動
docker compose up -d

# 2. ROS2 ビルドと起動
source /opt/ros/jazzy/setup.bash
colcon build --packages-select voicevox_speaker
source install/setup.bash
ros2 launch voicevox_speaker voicevox_speaker.launch.py

# 3. ブラウザで http://localhost:8080 を開きフォームから発話テスト

# 4. トピック監視（別ターミナル）
ros2 topic echo /voicevox/speak
ros2 topic echo /voicevox/status
```
