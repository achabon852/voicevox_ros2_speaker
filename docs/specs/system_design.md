# VOICEVOX ロボット発話システム — 設計書

| 項目 | 内容 |
|------|------|
| バージョン | 1.0 |
| 作成日 | 2026-06-28 |
| 対象ブランチ | main |

---

## 1. 目的・背景

VOICEVOX を用いた音声合成を PC 上で行い、合成した音声を ROS2 ネットワーク経由でロボットのスピーカーから再生するシステム。

- **音声合成**は計算コストが高いため PC 側に集約する
- **音声再生**はロボット側で行い、どのロボットでも `player_node` を起動するだけで対応できる汎用設計とする
- Web UI・ROS2 CLI の両方から発話をトリガーできる

---

## 2. システム全体構成

```mermaid
graph TB
    subgraph Browser["ブラウザ (Windows)"]
        UI["Web UI<br/>index.html"]
    end

    subgraph PC["PC — WSL2 Ubuntu (Docker)"]
        subgraph voicevox_container["voicevox コンテナ"]
            VV["VOICEVOX Engine<br/>:50021"]
        end
        subgraph ros2_container["ros2 コンテナ (network_mode: host)"]
            RB["rosbridge_websocket<br/>:9090"]
            SN["synth_node"]
            WEB["http.server<br/>:8080"]
        end
        CX["cyclonedds.xml<br/>(eth0 固定 / robot peer)"]
    end

    subgraph Robot["ロボット — Raspberry Pi (ROS2 Jazzy ネイティブ)"]
        PN["player_node"]
        SPK["スピーカー<br/>(aplay)"]
    end

    CLI["speak_cli<br/>(PC or ロボット)"]

    UI -- "HTTP :8080" --> WEB
    UI -- "WebSocket :9090" --> RB
    RB -- "/voicevox/speak<br/>pub" --> SN
    SN -- "REST API" --> VV
    VV -- "WAV bytes" --> SN
    SN -- "/voicevox/audio<br/>pub" --> PN
    SN -- "/voicevox/status<br/>pub" --> RB
    RB -- "WebSocket" --> UI
    PN --> SPK
    CLI -- "/voicevox/speak<br/>pub (DDS)" --> SN
    CX -. "CYCLONEDDS_URI" .-> ros2_container

    style PC fill:#e8f4f8,stroke:#2196F3
    style Robot fill:#e8f5e9,stroke:#4CAF50
    style Browser fill:#fff3e0,stroke:#FF9800
```

---

## 3. ネットワーク・デプロイ設計

### 3.1 ポート・プロトコル一覧

| ポート | プロトコル | 用途 |
|--------|-----------|------|
| 8080 | HTTP | Web UI 静的ファイル配信 |
| 9090 | WebSocket | rosbridge（ブラウザ ↔ ROS2） |
| 50021 | HTTP | VOICEVOX Engine REST API |
| — | UDP Multicast/Unicast | ROS2 DDS (CycloneDDS) |

### 3.2 WSL2 ネットワーク構成

```mermaid
graph LR
    subgraph Windows["Windows ホスト"]
        subgraph WSL2["WSL2 (172.25.x.x/20)"]
            subgraph Docker["Docker (network_mode: host)"]
                SN2["synth_node<br/>eth0: 172.25.204.25"]
            end
        end
        LAN_IF["物理 NIC<br/>192.168.1.x"]
    end
    Robot2["ロボット<br/>192.168.1.98"]

    SN2 -- "DDS (unicast peer)<br/>Windows ルーティング経由" --> Robot2
    Robot2 -- "DDS" --> SN2
    LAN_IF --- Robot2

    style WSL2 fill:#e3f2fd,stroke:#1565C0
    style Docker fill:#bbdefb,stroke:#1976D2
```

> WSL2 の eth0 は LAN（192.168.1.x）と異なるサブネット（172.25.x.x）に存在する。
> `cyclonedds.xml` でロボットの IP を peer に明示することで CycloneDDS の到達性を確保する。

### 3.3 CycloneDDS 設定 (`cyclonedds.xml`)

```xml
<CycloneDDS>
  <Domain>
    <General>
      <Interfaces>
        <NetworkInterface name="eth0" multicast="true"/>
      </Interfaces>
    </General>
    <Discovery>
      <Peers>
        <Peer address="<ロボットIP>"/>
      </Peers>
    </Discovery>
  </Domain>
</CycloneDDS>
```

---

## 4. ROS2 トピック設計

### 4.1 トピック一覧

| トピック名 | 型 | 方向 | QoS Depth | 説明 |
|-----------|-----|------|-----------|------|
| `/voicevox/speak` | `std_msgs/String` | 発話元 → synth_node | 10 | 発話リクエスト (JSON) |
| `/voicevox/audio` | `std_msgs/UInt8MultiArray` | synth_node → player_node | 10 | 合成済み WAV バイト列 |
| `/voicevox/status` | `std_msgs/String` | synth_node → ブラウザ | 10 | 状態通知 (JSON) |

### 4.2 メッセージスキーマ

**`/voicevox/speak`（発話リクエスト）**

```json
{
  "text": "こんにちは",
  "speaker_id": 2,
  "speed": 1.0,
  "volume": 1.0
}
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|-----|-----------|------|
| `text` | string | 必須 | 発話テキスト |
| `speaker_id` | int | 2 | VOICEVOX 話者 ID（四国めたん ノーマル） |
| `speed` | float | 1.0 | 速度（0.5 〜 2.0） |
| `volume` | float | 1.0 | 音量（0.0 〜 2.0） |

**`/voicevox/status`（状態通知）**

```json
{
  "state": "speaking",
  "message": "発話中: こんにちは"
}
```

| `state` 値 | 意味 |
|-----------|------|
| `idle` | 待機中 |
| `speaking` | 発話中 |
| `error` | エラー（VOICEVOX 接続失敗など） |

---

## 5. ノード詳細設計

### 5.1 synth_node

**役割**: 発話リクエストを受け取り、VOICEVOX で音声合成して WAV バイト列を配信する

```mermaid
classDiagram
    class SynthNode {
        -Queue _queue
        -Thread _worker_thread
        -Publisher _audio_pub
        -Publisher _status_pub
        -Subscription _speak_sub
        +__init__()
        -_on_speak(msg: String) void
        -_worker() void
        -_synthesise(data: dict) void
        -_clear_queue() void
        -_publish_status(state, message) void
    }
```

**処理フロー**

```mermaid
flowchart TD
    A(["/voicevox/speak 受信"]) --> B{JSON パース}
    B -- 失敗 --> B1["ERROR ログ\n処理中断"]
    B -- 成功 --> C{text が空?}
    C -- Yes --> C1["WARN ログ\n処理中断"]
    C -- No --> D{キュー満杯?}
    D -- Yes --> D1["最古エントリを破棄"] --> E
    D -- No --> E["キューに追加\n(maxsize=10)"]

    E --> F(["Worker スレッドが取得"])
    F --> G["status: speaking をパブリッシュ"]
    G --> H["VOICEVOX /audio_query 呼び出し\n(timeout=10s)"]
    H --> I["speedScale / volumeScale を適用"]
    I --> J["VOICEVOX /synthesis 呼び出し\n(timeout=30s)"]
    J --> K["/voicevox/audio に WAV をパブリッシュ"]
    K --> L["status: idle をパブリッシュ"]

    H -- 失敗 --> M{リトライ回数 < 3?}
    J -- 失敗 --> M
    M -- Yes --> N["1秒待機"] --> H
    M -- No --> O["キュークリア"]
    O --> P["status: error をパブリッシュ"]
```

**環境変数**

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `VOICEVOX_URL` | `http://localhost:50021` | VOICEVOX Engine の URL |

**定数**

| 定数 | 値 | 説明 |
|------|-----|------|
| `MAX_QUEUE_SIZE` | 10 | キュー最大長 |
| `MAX_RETRIES` | 3 | リトライ上限回数 |
| `RETRY_INTERVAL` | 1.0s | リトライ間隔 |

---

### 5.2 player_node

**役割**: `/voicevox/audio` を受信し、`aplay` でロボットスピーカーに再生する

```mermaid
classDiagram
    class PlayerNode {
        -Subscription _audio_sub
        +__init__()
        -_on_audio(msg: UInt8MultiArray) void
    }
```

**処理フロー**

```mermaid
flowchart TD
    A(["/voicevox/audio 受信\n(UInt8MultiArray)"]) --> B["bytes 変換\nwav_bytes = bytes(msg.data)"]
    B --> C["INFO: Playing N bytes"]
    C --> D["aplay -q - を stdin 経由で実行"]
    D -- 成功 --> E(["完了"])
    D -- FileNotFoundError --> F["ERROR: aplay not found\nsudo apt install alsa-utils"]
    D -- CalledProcessError --> G["ERROR: aplay exited with error"]
    D -- TimeoutExpired --> H["ERROR: aplay timed out"]
```

---

### 5.3 speak_cli

**役割**: コマンドライン引数からワンショットで `/voicevox/speak` に発話リクエストを送る

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant CLI as speak_cli_node
    participant DDS as ROS2 DDS
    participant SN as synth_node

    User->>CLI: ros2 run voicevox_speaker speak_cli "テキスト"
    CLI->>CLI: rclpy.init() / publisher 作成
    CLI->>CLI: sleep(0.5s) — DDS peer discovery 待機
    CLI->>DDS: /voicevox/speak publish
    DDS->>SN: メッセージ配信
    CLI->>CLI: spin_once(0.3s) — flush 待機
    CLI->>CLI: destroy / shutdown
```

**CLI 引数**

| 引数 | 型 | デフォルト | 説明 |
|------|-----|-----------|------|
| `text` | positional | 必須 | 発話テキスト |
| `--speaker-id` | int | 2 | 話者 ID |
| `--speed` | float | 1.0 | 速度（0.5〜2.0） |
| `--volume` | float | 1.0 | 音量（0.0〜2.0） |

---

## 6. エンドツーエンド シーケンス

### 6.1 Web UI からの発話

```mermaid
sequenceDiagram
    participant B as ブラウザ
    participant RB as rosbridge
    participant SN as synth_node
    participant VV as VOICEVOX Engine
    participant PN as player_node
    participant SPK as ロボットスピーカー

    B->>RB: WebSocket 接続
    RB-->>B: 接続確立
    B->>RB: subscribe /voicevox/status
    SN-->>RB: status: idle
    RB-->>B: 待機中 表示

    B->>RB: publish /voicevox/speak (JSON)
    RB->>SN: /voicevox/speak

    SN-->>RB: status: speaking
    RB-->>B: 発話中 表示 / ボタン無効化

    SN->>VV: POST /audio_query
    VV-->>SN: audio_query JSON
    SN->>VV: POST /synthesis
    VV-->>SN: WAV bytes (~45KB)

    SN->>PN: /voicevox/audio (UInt8MultiArray)
    PN->>SPK: aplay -q - (stdin)
    SPK-->>PN: 再生完了

    SN-->>RB: status: idle
    RB-->>B: 待機中 表示 / ボタン有効化
```

### 6.2 ROS2 CLI からの発話（ロボット側 speak_cli）

```mermaid
sequenceDiagram
    participant CLI as speak_cli<br/>(ロボット)
    participant SN as synth_node<br/>(PC Docker)
    participant VV as VOICEVOX Engine
    participant PN as player_node<br/>(ロボット)

    CLI->>CLI: DDS peer discovery (0.5s)
    CLI->>SN: /voicevox/speak (DDS unicast)
    SN->>VV: POST /audio_query
    VV-->>SN: audio_query JSON
    SN->>VV: POST /synthesis
    VV-->>SN: WAV bytes
    SN->>PN: /voicevox/audio (DDS)
    PN->>PN: aplay で再生
    CLI->>CLI: flush wait (0.3s) → 終了
```

### 6.3 エラーリトライシーケンス

```mermaid
sequenceDiagram
    participant SN as synth_node
    participant VV as VOICEVOX Engine

    SN->>VV: POST /audio_query (attempt 1)
    VV--x SN: タイムアウト or エラー
    SN->>SN: WARN: Attempt 1/3 failed

    Note over SN: sleep 1.0s

    SN->>VV: POST /audio_query (attempt 2)
    VV--x SN: エラー
    SN->>SN: WARN: Attempt 2/3 failed

    Note over SN: sleep 1.0s

    SN->>VV: POST /audio_query (attempt 3)
    VV--x SN: エラー
    SN->>SN: WARN: Attempt 3/3 failed
    SN->>SN: キュークリア
    SN-->>SN: status: error パブリッシュ
```

---

## 7. コンポーネント間の依存関係

```mermaid
graph LR
    subgraph ROS2パッケージ["voicevox_speaker パッケージ"]
        SN["synth_node.py"]
        PN["player_node.py"]
        CLI["speak_cli.py"]
        SN_old["speaker_node.py<br/>(旧・互換性維持)"]
    end

    subgraph LaunchFiles["Launch ファイル"]
        L1["voicevox_synth.launch.py<br/>(PC側)"]
        L2["voicevox_player.launch.py<br/>(ロボット側)"]
        L3["voicevox_speaker.launch.py<br/>(旧・ローカル再生)"]
    end

    subgraph External["外部依存"]
        RCLPY["rclpy"]
        STD["std_msgs"]
        RB_PKG["rosbridge_server"]
        REQ["requests"]
        APLAY["aplay<br/>(alsa-utils)"]
        VV_ENG["VOICEVOX Engine<br/>(Docker)"]
    end

    L1 --> SN
    L1 --> RB_PKG
    L2 --> PN
    L3 --> SN_old

    SN --> RCLPY
    SN --> STD
    SN --> REQ
    SN --> VV_ENG

    PN --> RCLPY
    PN --> STD
    PN --> APLAY

    CLI --> RCLPY
    CLI --> STD
```

---

## 8. ファイル構成

```
voicevox_ros2_jazzy/
├── Dockerfile                          # ros2 コンテナ定義（tiryoh/ros2:jazzy ベース）
├── docker-compose.yml                  # VOICEVOX + ros2 コンテナ起動定義
├── docker-entrypoint.sh                # コンテナ起動スクリプト（voicevox_synth.launch.py）
├── cyclonedds.xml                      # CycloneDDS NIC・peer 設定（ロボットIP要編集）
├── README.md
├── docs/
│   └── specs/
│       ├── system_design.md            # 本設計書
│       └── voicevox_web_speaker.md     # 旧要件定義書
└── src/voicevox_speaker/
    ├── package.xml
    ├── setup.py
    ├── setup.cfg
    ├── requirements.txt
    ├── resource/voicevox_speaker
    ├── voicevox_speaker/
    │   ├── __init__.py
    │   ├── synth_node.py               # PC側: 音声合成 → /voicevox/audio
    │   ├── player_node.py              # ロボット側: /voicevox/audio → aplay
    │   ├── speak_cli.py                # CLI発話ツール
    │   └── speaker_node.py            # 旧: PCローカル再生（互換性維持）
    ├── launch/
    │   ├── voicevox_synth.launch.py    # PC側: rosbridge + synth_node + Web UI
    │   ├── voicevox_player.launch.py   # ロボット側: player_node
    │   └── voicevox_speaker.launch.py  # 旧: PCローカル再生
    ├── web/
    │   ├── index.html                  # Web UI（roslibjs 使用）
    │   └── roslib.min.js               # roslibjs ローカルバンドル
    └── test/
        ├── conftest.py
        └── test_speaker_logic.py
```

---

## 9. 環境変数・設定一覧

| 変数名 | 設定場所 | デフォルト | 説明 |
|--------|---------|-----------|------|
| `ROS_DOMAIN_ID` | docker-compose.yml / ロボット | 0 | DDS ドメイン（PC・ロボット共通） |
| `RMW_IMPLEMENTATION` | docker-entrypoint.sh / ロボット | — | `rmw_cyclonedds_cpp` 固定 |
| `VOICEVOX_URL` | docker-compose.yml | `http://localhost:50021` | VOICEVOX Engine URL |
| `CYCLONEDDS_URI` | docker-compose.yml | — | `file:///etc/cyclonedds.xml` |

---

## 10. 非機能要件・制約

| 項目 | 内容 |
|------|------|
| 発話キュー上限 | 10 件（超過時は最古を破棄） |
| VOICEVOX リトライ | 最大 3 回、間隔 1 秒 |
| 音声合成タイムアウト | `/audio_query`: 10 秒、`/synthesis`: 30 秒 |
| 音声再生タイムアウト | 60 秒 |
| 同時発話 | 非対応（キューで順次処理） |
| 認証・アクセス制限 | なし（LAN 内デモ用途） |
| ホスト WSL2 への ROS2 インストール | 不要（Docker コンテナ完結） |
