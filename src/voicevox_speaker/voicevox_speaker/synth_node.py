"""ROS2 node: synthesise speech via VOICEVOX and publish WAV bytes to /voicevox/audio."""
import json
import os
import queue
import threading
import time

import requests
import rclpy
from rclpy.node import Node
from std_msgs.msg import String, UInt8MultiArray

VOICEVOX_BASE_URL = os.environ.get('VOICEVOX_URL', 'http://localhost:50021')
MAX_QUEUE_SIZE = 10
MAX_RETRIES = 3
RETRY_INTERVAL = 1.0


class SynthNode(Node):

    def __init__(self) -> None:
        super().__init__('synth_node')
        self._speak_sub = self.create_subscription(
            String, '/voicevox/speak', self._on_speak, 10
        )
        self._audio_pub = self.create_publisher(UInt8MultiArray, '/voicevox/audio', 10)
        self._status_pub = self.create_publisher(String, '/voicevox/status', 10)
        self._queue: queue.Queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        self._publish_status('idle', '待機中')

    # ------------------------------------------------------------------
    # Subscription callback (ROS2 executor thread)
    # ------------------------------------------------------------------

    def _on_speak(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError as e:
            self.get_logger().error(f'Invalid JSON in /voicevox/speak: {e}')
            return

        text = data.get('text', '').strip()
        if not text:
            self.get_logger().warn('Empty text received, ignoring.')
            return

        if self._queue.full():
            try:
                discarded = self._queue.get_nowait()
                label = str(discarded.get('text', ''))[:20]
                self.get_logger().warn(f'Queue full — discarding oldest: "{label}"')
            except queue.Empty:
                pass

        self._queue.put(data)
        self.get_logger().info(
            f'Queued: "{text[:30]}" (queue depth: {self._queue.qsize()})'
        )

    # ------------------------------------------------------------------
    # Worker thread (processes queue sequentially)
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                self._synthesise(item)
            except Exception as e:
                self.get_logger().error(f'Unexpected error in worker: {e}')
                self._publish_status('idle', '待機中')
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------
    # Speech synthesis — publishes WAV bytes (called from worker thread)
    # ------------------------------------------------------------------

    def _synthesise(self, data: dict) -> None:
        text = data.get('text', '')
        speaker_id = int(data.get('speaker_id', 2))
        speed = float(data.get('speed', 1.0))
        volume = float(data.get('volume', 1.0))

        self._publish_status('speaking', f'発話中: {text[:20]}')

        for attempt in range(MAX_RETRIES):
            try:
                # Step 1: generate audio query
                resp = requests.post(
                    f'{VOICEVOX_BASE_URL}/audio_query',
                    params={'text': text, 'speaker': speaker_id},
                    timeout=10,
                )
                resp.raise_for_status()
                audio_query = resp.json()
                audio_query['speedScale'] = speed
                audio_query['volumeScale'] = volume

                # Step 2: synthesise WAV
                resp = requests.post(
                    f'{VOICEVOX_BASE_URL}/synthesis',
                    params={'speaker': speaker_id},
                    json=audio_query,
                    timeout=30,
                )
                resp.raise_for_status()

                # Step 3: publish WAV bytes — any player_node on the same domain plays it
                audio_msg = UInt8MultiArray()
                audio_msg.data = list(resp.content)
                self._audio_pub.publish(audio_msg)
                self.get_logger().info(
                    f'Audio published: {len(resp.content)} bytes'
                )

                self._publish_status('idle', '待機中')
                return

            except Exception as e:
                self.get_logger().warn(f'Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}')
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_INTERVAL)

        self._clear_queue()
        self._publish_status('error', 'VOICEVOX に接続できませんでした')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clear_queue(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _publish_status(self, state: str, message: str) -> None:
        status_msg = String()
        status_msg.data = json.dumps(
            {'state': state, 'message': message}, ensure_ascii=False
        )
        self._status_pub.publish(status_msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SynthNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
