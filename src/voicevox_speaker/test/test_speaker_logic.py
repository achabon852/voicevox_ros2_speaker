"""Unit tests for speaker_node pure logic.

ROS2 and audio dependencies are mocked via sys.modules before the module
under test is imported, so these tests run on any Python 3.10+ environment
without ROS2 or audio hardware.
"""
import json
import queue
import sys
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Mock ROS2 and audio dependencies BEFORE importing the module under test.
# _FakeNode is a real class so SpeakerNode can subclass it without issues.
# ---------------------------------------------------------------------------

class _FakeNode:
    """Minimal stand-in for rclpy.node.Node."""

    def __init__(self, name: str) -> None:
        self._name = name

    def create_subscription(self, *args, **kwargs):  # noqa: ANN
        return MagicMock()

    def create_publisher(self, *args, **kwargs):  # noqa: ANN
        return MagicMock()

    def get_logger(self):  # noqa: ANN
        return MagicMock()


_mock_rclpy_node = MagicMock()
_mock_rclpy_node.Node = _FakeNode

sys.modules.setdefault('rclpy', MagicMock())
sys.modules['rclpy.node'] = _mock_rclpy_node
sys.modules.setdefault('std_msgs', MagicMock())
sys.modules.setdefault('std_msgs.msg', MagicMock())
sys.modules.setdefault('sounddevice', MagicMock())
sys.modules.setdefault('soundfile', MagicMock())
sys.modules.setdefault('requests', MagicMock())

from voicevox_speaker.speaker_node import SpeakerNode, MAX_QUEUE_SIZE  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_node() -> SpeakerNode:
    """Return a SpeakerNode without starting ROS2 or the worker thread."""
    node = SpeakerNode.__new__(SpeakerNode)
    node._queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
    node._status_pub = MagicMock()
    node.get_logger = MagicMock(return_value=MagicMock())
    return node


def _speak_msg(text: str = 'hello', speaker_id: int = 2,
               speed: float = 1.0, volume: float = 1.0) -> MagicMock:
    msg = MagicMock()
    msg.data = json.dumps({
        'text': text, 'speaker_id': speaker_id,
        'speed': speed, 'volume': volume,
    })
    return msg


# ---------------------------------------------------------------------------
# _on_speak tests
# ---------------------------------------------------------------------------

class TestOnSpeak(unittest.TestCase):

    def setUp(self) -> None:
        self.node = _make_node()

    def test_valid_message_is_queued(self) -> None:
        self.node._on_speak(_speak_msg('こんにちは'))
        self.assertEqual(self.node._queue.qsize(), 1)

    def test_invalid_json_is_ignored(self) -> None:
        msg = MagicMock()
        msg.data = 'not json {{{'
        self.node._on_speak(msg)
        self.assertEqual(self.node._queue.qsize(), 0)

    def test_empty_text_is_ignored(self) -> None:
        self.node._on_speak(_speak_msg(text='   '))
        self.assertEqual(self.node._queue.qsize(), 0)

    def test_whitespace_only_text_is_ignored(self) -> None:
        self.node._on_speak(_speak_msg(text='\t\n'))
        self.assertEqual(self.node._queue.qsize(), 0)

    def test_queue_overflow_discards_oldest(self) -> None:
        for i in range(MAX_QUEUE_SIZE):
            self.node._on_speak(_speak_msg(text=f'msg{i}'))
        self.assertEqual(self.node._queue.qsize(), MAX_QUEUE_SIZE)

        self.node._on_speak(_speak_msg(text='new_msg'))

        self.assertEqual(self.node._queue.qsize(), MAX_QUEUE_SIZE)
        texts = [item['text'] for item in list(self.node._queue.queue)]
        self.assertNotIn('msg0', texts, 'oldest item should be discarded')
        self.assertIn('new_msg', texts, 'newest item should be present')

    def test_queue_overflow_keeps_newer_items(self) -> None:
        for i in range(MAX_QUEUE_SIZE):
            self.node._on_speak(_speak_msg(text=f'msg{i}'))
        self.node._on_speak(_speak_msg(text='newest'))
        texts = [item['text'] for item in list(self.node._queue.queue)]
        for i in range(1, MAX_QUEUE_SIZE):
            self.assertIn(f'msg{i}', texts)

    def test_queued_data_contains_all_fields(self) -> None:
        self.node._on_speak(_speak_msg('hi', speaker_id=3, speed=1.5, volume=0.8))
        item = self.node._queue.get_nowait()
        self.assertEqual(item['text'], 'hi')
        self.assertEqual(item['speaker_id'], 3)
        self.assertAlmostEqual(item['speed'], 1.5)
        self.assertAlmostEqual(item['volume'], 0.8)


# ---------------------------------------------------------------------------
# _publish_status tests
# ---------------------------------------------------------------------------

class TestPublishStatus(unittest.TestCase):

    def setUp(self) -> None:
        self.node = _make_node()

    def _last_published(self) -> dict:
        msg = self.node._status_pub.publish.call_args[0][0]
        return json.loads(msg.data)

    def test_publishes_correct_state_and_message(self) -> None:
        self.node._publish_status('speaking', '発話中')
        data = self._last_published()
        self.assertEqual(data['state'], 'speaking')
        self.assertEqual(data['message'], '発話中')

    def test_idle_state(self) -> None:
        self.node._publish_status('idle', '待機中')
        self.assertEqual(self._last_published()['state'], 'idle')

    def test_error_state(self) -> None:
        self.node._publish_status('error', 'エラー')
        self.assertEqual(self._last_published()['state'], 'error')

    def test_japanese_message_is_preserved(self) -> None:
        self.node._publish_status('idle', '日本語メッセージ')
        self.assertEqual(self._last_published()['message'], '日本語メッセージ')


# ---------------------------------------------------------------------------
# _clear_queue tests
# ---------------------------------------------------------------------------

class TestClearQueue(unittest.TestCase):

    def setUp(self) -> None:
        self.node = _make_node()

    def test_empties_queue(self) -> None:
        for i in range(5):
            self.node._queue.put({'text': f'item{i}'})
        self.node._clear_queue()
        self.assertTrue(self.node._queue.empty())

    def test_noop_on_empty_queue(self) -> None:
        self.node._clear_queue()
        self.assertTrue(self.node._queue.empty())

    def test_full_queue_becomes_empty(self) -> None:
        for i in range(MAX_QUEUE_SIZE):
            self.node._queue.put({'text': f'item{i}'})
        self.node._clear_queue()
        self.assertTrue(self.node._queue.empty())


# ---------------------------------------------------------------------------
# _speak tests (VOICEVOX API calls, playback, retry, error handling)
# ---------------------------------------------------------------------------

class TestSpeak(unittest.TestCase):

    def setUp(self) -> None:
        self.node = _make_node()
        # Reset mocked modules to a clean state for each test
        sys.modules['requests'].post.reset_mock()
        sys.modules['requests'].post.side_effect = None
        sys.modules['sounddevice'].play.reset_mock()
        sys.modules['sounddevice'].wait.reset_mock()
        sys.modules['soundfile'].read.reset_mock()
        sys.modules['soundfile'].read.side_effect = None

    # -- helpers ------------------------------------------------------------

    def _setup_success(self, speed: float = 1.0, volume: float = 1.0) -> dict:
        """Configure mocks for a successful VOICEVOX + playback call."""
        query_data = {'speedScale': speed, 'volumeScale': volume}
        aq_resp = MagicMock()
        aq_resp.json.return_value = query_data
        syn_resp = MagicMock()
        syn_resp.content = b'RIFF\x00\x00\x00\x00WAVEfmt '
        sys.modules['requests'].post.side_effect = [aq_resp, syn_resp]
        sys.modules['soundfile'].read.return_value = (MagicMock(), 22050)
        return query_data

    def _payload(self, text='test', speaker_id=2, speed=1.0, volume=1.0):
        return {'text': text, 'speaker_id': speaker_id,
                'speed': speed, 'volume': volume}

    # -- success path -------------------------------------------------------

    def test_makes_two_api_calls(self) -> None:
        self._setup_success()
        self.node._speak(self._payload())
        self.assertEqual(sys.modules['requests'].post.call_count, 2)

    def test_first_api_call_is_audio_query(self) -> None:
        self._setup_success()
        self.node._speak(self._payload(text='hello', speaker_id=3))
        first = sys.modules['requests'].post.call_args_list[0]
        self.assertIn('audio_query', first.args[0])
        self.assertEqual(first.kwargs['params']['speaker'], 3)
        self.assertEqual(first.kwargs['params']['text'], 'hello')

    def test_second_api_call_is_synthesis(self) -> None:
        self._setup_success()
        self.node._speak(self._payload(speaker_id=3))
        second = sys.modules['requests'].post.call_args_list[1]
        self.assertIn('synthesis', second.args[0])
        self.assertEqual(second.kwargs['params']['speaker'], 3)

    def test_speed_and_volume_applied_to_audio_query(self) -> None:
        query_data = self._setup_success(speed=1.5, volume=0.8)
        self.node._speak(self._payload(speed=1.5, volume=0.8))
        # query_data is mutated in-place before being passed to synthesis
        self.assertAlmostEqual(query_data['speedScale'], 1.5)
        self.assertAlmostEqual(query_data['volumeScale'], 0.8)

    def test_audio_is_played(self) -> None:
        self._setup_success()
        self.node._speak(self._payload())
        sys.modules['sounddevice'].play.assert_called_once()
        sys.modules['sounddevice'].wait.assert_called_once()

    def test_success_publishes_idle_status(self) -> None:
        self._setup_success()
        self.node._speak(self._payload())
        last = self.node._status_pub.publish.call_args[0][0]
        self.assertEqual(json.loads(last.data)['state'], 'idle')

    # -- retry / error path -------------------------------------------------

    def test_retries_three_times_on_failure(self) -> None:
        sys.modules['requests'].post.side_effect = ConnectionError('refused')
        with patch('voicevox_speaker.speaker_node.time') as mock_time:
            self.node._speak(self._payload())
        self.assertEqual(sys.modules['requests'].post.call_count, 3)
        # sleep is called between attempts (not after the last one)
        self.assertEqual(mock_time.sleep.call_count, 2)

    def test_sleep_uses_retry_interval(self) -> None:
        from voicevox_speaker.speaker_node import RETRY_INTERVAL
        sys.modules['requests'].post.side_effect = ConnectionError('refused')
        with patch('voicevox_speaker.speaker_node.time') as mock_time:
            self.node._speak(self._payload())
        for call in mock_time.sleep.call_args_list:
            self.assertAlmostEqual(call.args[0], RETRY_INTERVAL)

    def test_total_failure_publishes_error_status(self) -> None:
        sys.modules['requests'].post.side_effect = ConnectionError('refused')
        with patch('voicevox_speaker.speaker_node.time'):
            self.node._speak(self._payload())
        last = self.node._status_pub.publish.call_args[0][0]
        self.assertEqual(json.loads(last.data)['state'], 'error')

    def test_total_failure_clears_queue(self) -> None:
        self.node._queue.put({'text': 'queued_item'})
        sys.modules['requests'].post.side_effect = ConnectionError('refused')
        with patch('voicevox_speaker.speaker_node.time'):
            self.node._speak(self._payload())
        self.assertTrue(self.node._queue.empty())

    def test_success_on_second_attempt(self) -> None:
        query_data = {'speedScale': 1.0, 'volumeScale': 1.0}
        aq_resp = MagicMock()
        aq_resp.json.return_value = query_data
        syn_resp = MagicMock()
        syn_resp.content = b'wav_data'
        # First attempt raises; second succeeds
        sys.modules['requests'].post.side_effect = [
            ConnectionError('refused'),
            aq_resp,
            syn_resp,
        ]
        sys.modules['soundfile'].read.return_value = (MagicMock(), 22050)
        with patch('voicevox_speaker.speaker_node.time'):
            self.node._speak(self._payload())
        # post called 3 times (1 failed + audio_query + synthesis)
        self.assertEqual(sys.modules['requests'].post.call_count, 3)
        last = self.node._status_pub.publish.call_args[0][0]
        self.assertEqual(json.loads(last.data)['state'], 'idle')


if __name__ == '__main__':
    unittest.main()
