# VOICEVOX ロボット発話システム — ROS2 Jazzy

ブラウザのフォームまたは ROS2 コマンドからテキストを送ると、VOICEVOX が音声合成し、ロボット（ライトローバー等）のスピーカーから再生されます。

音声合成（VOICEVOX）は PC 上の Docker コンテナで行い、再生はロボット側の `player_node` が担うため、**どんなロボットでも `player_node` を動かすだけで対応できます**。

---

## システム構成

```
[ブラウザ / ROS2 CLI]
   │  HTTP (port 8080)  WebSocket (port 9090)
   ▼
[PC — WSL2 / Ubuntu, Docker]
   ├── voicevox コンテナ  (localhost:50021)
   └── ros2 コンテナ  (network_mode: host)
         ├── rosbridge_websocket  :9090
         ├── synth_node            ← /voicevox/speak → VOICEVOX API → /voicevox/audio
         └── python http.server   :8080  (Web UI)

         ↕  ROS2 DDS (CycloneDDS, 同一 ROS_DOMAIN_ID, 同一 LAN)

[ロボット — ROS2 Jazzy ネイティブ]
   └── player_node                ← /voicevox/audio → paplay → ロボットスピーカー
```

### ROS2 トピック

| トピック | 型 | 説明 |
|---------|-----|------|
| `/voicevox/speak` | `std_msgs/String` (JSON) | 発話リクエスト |
| `/voicevox/audio` | `std_msgs/UInt8MultiArray` | 合成済み WAV バイト列 |
| `/voicevox/status` | `std_msgs/String` (JSON) | 発話状態 (idle/speaking/error) |

`/voicevox/speak` の JSON ペイロード例:
```json
{"text": "こんにちは", "speaker_id": 2, "speed": 1.0, "volume": 1.0}
```

---

## 前提条件

### PC 側 (WSL2 / Ubuntu)

| 項目 | バージョン |
|------|-----------|
| WSL2 | Ubuntu 24.04 LTS |
| Docker Engine | 26.0 以上（Compose v2 付属） |

### ロボット側

| 項目 | 要件 |
|------|------|
| OS | Ubuntu 24.04 LTS (推奨) |
| ROS2 | Jazzy Jalisco |
| 音声再生 | `pulseaudio-utils`（`paplay` コマンド） |
| ネットワーク | PC と同一 LAN |

---

## PC 側のセットアップと起動

### 1. Docker Engine のインストール（WSL2 Ubuntu 内）

```bash
sudo apt update && sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) stable" \
    | sudo tee /etc/apt/sources/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
                   docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker
```

### 2. ROS_DOMAIN_ID を決める

ロボット側と **同じ値** を使います（0〜232 の整数）。ここでは例として `10` を使用。

```bash
export ROS_DOMAIN_ID=10
```

`.bashrc` に書いておくと毎回不要です:
```bash
echo 'export ROS_DOMAIN_ID=10' >> ~/.bashrc
```

### 3. コンテナをビルド・起動

```bash
cd ~/voicevox_ros2_jazzy

# 初回：イメージビルド込みで起動
ROS_DOMAIN_ID=10 docker compose up --build -d

# 2回目以降
ROS_DOMAIN_ID=10 docker compose up -d
```

### 4. 起動確認

```bash
docker compose ps
curl http://localhost:50021/version   # VOICEVOX が応答すれば OK
docker compose logs ros2 --follow
```

ログに以下が出れば起動完了:
```
[rosbridge_websocket]: Rosbridge WebSocket server started on port 9090
[synth_node]: Publishing: {"state": "idle", "message": "待機中"}
Serving HTTP on 0.0.0.0 port 8080
```

---

## ロボット側のセットアップと起動

### 1. ROS2 Jazzy と依存パッケージのインストール

```bash
# ROS2 Jazzy（公式手順 https://docs.ros.org/en/jazzy/Installation.html）

# 依存パッケージ
sudo apt install -y \
    ros-jazzy-rmw-cyclonedds-cpp \
    pulseaudio-utils \
    python3-pip
```

### 2. このリポジトリをクローン・ビルド

```bash
mkdir -p ~/ros2_ws/src
cd ~/ros2_ws/src
git clone <このリポジトリのURL> voicevox_speaker

cd ~/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select voicevox_speaker
source install/setup.bash
```

### 3. ROS_DOMAIN_ID を PC 側と合わせて player_node を起動

```bash
export ROS_DOMAIN_ID=10
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch voicevox_speaker voicevox_player.launch.py
```

ログに `player_node ready — listening on /voicevox/audio` が出れば準備完了です。

---

## 発話方法

### A) Web ブラウザから

```
http://<PC の IP アドレス>:8080
```

話者・速度・音量を選んでテキストを入力し「発話」ボタンをクリック。

### B) ROS2 コマンドラインから

ホスト WSL2 に ROS2 をインストールせずに使う場合は、`docker compose exec` 経由で ros2 コンテナ内のコマンドを実行します。

**`speak_cli` ツール（推奨）**

```bash
# PC 側（ホスト WSL2 から docker compose exec 経由）
docker compose exec ros2 ros2 run voicevox_speaker speak_cli "こんにちは"

# パラメータ指定
docker compose exec ros2 ros2 run voicevox_speaker speak_cli "ロボットです" \
    --speaker-id 3 --speed 1.2 --volume 1.5

# ヘルプ
docker compose exec ros2 ros2 run voicevox_speaker speak_cli --help
```

ロボット側（ROS2 Jazzy ネイティブ環境）から実行する場合:

```bash
ros2 run voicevox_speaker speak_cli "こんにちは"
```

**`ros2 topic pub` で直接送る場合**

```bash
# PC 側（docker compose exec 経由）
docker compose exec ros2 ros2 topic pub --once /voicevox/speak std_msgs/String \
  '{"data": "{\"text\": \"こんにちは\", \"speaker_id\": 2, \"speed\": 1.0, \"volume\": 1.0}"}'
```

---

## 停止手順

```bash
# PC 側コンテナ停止
docker compose down

# ロボット側
# Ctrl+C で player_node を停止
```

---

## トラブルシューティング

### ロボットに音声が届かない（/voicevox/audio が受信されない）

**確認1: ROS_DOMAIN_ID が一致しているか**

```bash
# PC 側（コンテナ内）
docker compose exec ros2 bash -c 'echo $ROS_DOMAIN_ID'

# ロボット側
echo $ROS_DOMAIN_ID
```

**確認2: トピックがロボットから見えるか**

```bash
# ロボット側で実行
ros2 topic list | grep voicevox
ros2 topic echo /voicevox/audio --no-arr   # メッセージ受信を確認
```

**確認3: CycloneDDS のネットワークインタフェース設定**

WSL2 や複数 NIC 環境では、CycloneDDS が正しいインタフェースを選択できないことがあります。
以下のように明示的に指定してください:

```bash
# PC 側（WSL2）のインタフェース名を確認
ip link show

# 例: eth0 を指定
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><NetworkInterfaceAddress>eth0</NetworkInterfaceAddress></General></Domain></CycloneDDS>'
```

`docker-compose.yml` に追記する場合:
```yaml
environment:
  - CYCLONEDDS_URI=<CycloneDDS><Domain><General><NetworkInterfaceAddress>eth0</NetworkInterfaceAddress></General></Domain></CycloneDDS>
```

### 音が出ない（player_node のログにエラーが出る）

```bash
# paplay がインストールされているか確認
which paplay || sudo apt install -y pulseaudio-utils

# PulseAudio が動作しているか確認
paplay /usr/share/sounds/alsa/Front_Left.wav
```

### ブラウザから接続できない

```bash
# WSL2 の IP を確認してブラウザでアクセス
hostname -I | awk '{print $1}'
# http://<上記IP>:8080
```

---

## ディレクトリ構成

```
.
├── Dockerfile
├── docker-entrypoint.sh
├── docker-compose.yml
├── README.md
├── docs/specs/voicevox_web_speaker.md
└── src/voicevox_speaker/
    ├── package.xml
    ├── setup.py
    ├── requirements.txt
    ├── voicevox_speaker/
    │   ├── synth_node.py       # PC側: 音声合成 → /voicevox/audio パブリッシュ
    │   ├── player_node.py      # ロボット側: /voicevox/audio → スピーカー再生
    │   ├── speak_cli.py        # CLI発話ツール
    │   └── speaker_node.py     # (旧) PCローカル再生用（互換性維持）
    ├── launch/
    │   ├── voicevox_synth.launch.py    # PC側起動（rosbridge + synth_node + Web UI）
    │   ├── voicevox_player.launch.py   # ロボット側起動（player_node）
    │   └── voicevox_speaker.launch.py  # (旧) PCローカル再生用
    └── web/
        ├── index.html
        └── roslib.min.js
```
