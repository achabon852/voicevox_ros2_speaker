"""Launch rosbridge_websocket, synth_node, and a static HTTP server (PC side)."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    web_dir = os.path.join(
        get_package_share_directory('voicevox_speaker'), 'web'
    )

    return LaunchDescription([
        # rosbridge WebSocket server — bridges browser / ROS2 CLI ↔ ROS2 topics
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            name='rosbridge_websocket',
            parameters=[{'port': 9090}],
            output='screen',
        ),

        # VOICEVOX synth node — converts /voicevox/speak → WAV → /voicevox/audio
        Node(
            package='voicevox_speaker',
            executable='synth_node',
            name='synth_node',
            output='screen',
        ),

        # Static HTTP server for the web UI (port 8080, LAN accessible)
        ExecuteProcess(
            cmd=['python3', '-m', 'http.server', '8080', '--bind', '0.0.0.0'],
            cwd=web_dir,
            name='web_http_server',
            output='screen',
        ),
    ])
