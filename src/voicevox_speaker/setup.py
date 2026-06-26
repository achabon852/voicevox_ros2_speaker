import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'voicevox_speaker'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'web'), glob('web/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Developer',
    maintainer_email='developer@example.com',
    description='VOICEVOX WEB Speaker Node for ROS2 Jazzy',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'speaker_node = voicevox_speaker.speaker_node:main',
            'synth_node    = voicevox_speaker.synth_node:main',
            'player_node   = voicevox_speaker.player_node:main',
            'speak_cli     = voicevox_speaker.speak_cli:main',
        ],
    },
)
