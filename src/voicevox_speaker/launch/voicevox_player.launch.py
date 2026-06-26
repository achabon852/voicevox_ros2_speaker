"""Launch player_node on the robot — subscribe /voicevox/audio and play on robot's speaker."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        # Audio player: receives WAV bytes from /voicevox/audio and plays via paplay
        Node(
            package='voicevox_speaker',
            executable='player_node',
            name='player_node',
            output='screen',
        ),
    ])
