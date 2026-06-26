"""ROS2 node: subscribe /voicevox/audio and play WAV on the robot's speaker via paplay."""
import subprocess

import rclpy
from rclpy.node import Node
from std_msgs.msg import UInt8MultiArray


class PlayerNode(Node):

    def __init__(self) -> None:
        super().__init__('player_node')
        self._audio_sub = self.create_subscription(
            UInt8MultiArray, '/voicevox/audio', self._on_audio, 10
        )
        self.get_logger().info('player_node ready — listening on /voicevox/audio')

    def _on_audio(self, msg: UInt8MultiArray) -> None:
        wav_bytes = bytes(msg.data)
        self.get_logger().info(f'Playing {len(wav_bytes)} bytes')
        try:
            subprocess.run(
                ['paplay'],
                input=wav_bytes,
                check=True,
                timeout=60,
            )
        except FileNotFoundError:
            self.get_logger().error(
                'paplay not found. Install pulseaudio-utils: sudo apt install pulseaudio-utils'
            )
        except subprocess.CalledProcessError as e:
            self.get_logger().error(f'paplay exited with error: {e}')
        except subprocess.TimeoutExpired:
            self.get_logger().error('paplay timed out')


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PlayerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
