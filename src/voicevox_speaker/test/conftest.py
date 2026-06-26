"""pytest configuration: add the package root to sys.path."""
import os
import sys

# Allow `import voicevox_speaker.speaker_node` without installing the package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
