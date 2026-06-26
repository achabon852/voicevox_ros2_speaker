"""CLI tool: publish a single speak request to /voicevox/speak and exit.

Usage:
    ros2 run voicevox_speaker speak_cli "こんにちは"
    ros2 run voicevox_speaker speak_cli "ロボットです" --speaker-id 3 --speed 1.2 --volume 1.5
"""
import argparse
import json
import sys
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

DISCOVERY_WAIT = 0.5   # seconds — time for DDS peer discovery before publishing
FLUSH_WAIT = 0.3       # seconds — time to let the message be transmitted


def _parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Publish a speak request to /voicevox/speak',
        prog='ros2 run voicevox_speaker speak_cli',
    )
    parser.add_argument('text', help='発話テキスト')
    parser.add_argument(
        '--speaker-id', type=int, default=2, metavar='ID',
        help='VOICEVOX 話者ID (デフォルト: 2 = 四国めたん ノーマル)',
    )
    parser.add_argument(
        '--speed', type=float, default=1.0,
        help='発話速度 0.5–2.0 (デフォルト: 1.0)',
    )
    parser.add_argument(
        '--volume', type=float, default=1.0,
        help='音量 0.0–2.0 (デフォルト: 1.0)',
    )
    return parser.parse_args(argv)


def main(args=None) -> None:
    rclpy.init(args=args)

    # Separate ROS args from our args
    our_argv = rclpy.utilities.remove_ros_args(args=sys.argv)[1:]
    parsed = _parse_args(our_argv)

    node = Node('speak_cli_node')
    pub = node.create_publisher(String, '/voicevox/speak', 1)

    # Wait for DDS peer discovery so synth_node receives the message
    time.sleep(DISCOVERY_WAIT)

    payload = {
        'text': parsed.text,
        'speaker_id': parsed.speaker_id,
        'speed': parsed.speed,
        'volume': parsed.volume,
    }
    msg = String()
    msg.data = json.dumps(payload, ensure_ascii=False)
    pub.publish(msg)
    node.get_logger().info(f'Speak request sent: {msg.data}')

    # Brief spin so the message is flushed before shutdown
    deadline = time.time() + FLUSH_WAIT
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)

    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
