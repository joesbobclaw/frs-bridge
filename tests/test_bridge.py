from array import array
import json
import math
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
import wave

from frs_bridge.api import server
from frs_bridge.core import RATE, Store, activity, effect, process, read_wav, write_wav
from frs_bridge.speakers import Registry
from frs_bridge.capture import capture


def signal(seconds=2, frequency=440):
    values = array("h", (int(6000 * math.sin(2*math.pi*frequency*i/RATE)) for i in range(int(RATE*seconds))))
    import sys
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "private")

    def tearDown(self):
        self.temp.cleanup()

    def test_silence_not_candidate(self):
        self.assertFalse(activity(bytes(RATE*4))["candidate"])

    def test_short_click_not_candidate(self):
        pcm = bytes(RATE) + signal(0.2) + bytes(RATE)
        self.assertFalse(activity(pcm)["candidate"])

    def test_synthetic_tone_is_candidate_not_proven_speech(self):
        self.assertTrue(activity(signal())["candidate"])

    def test_monotonic_persistent_cursors(self):
        first = self.store.emit({"type": "first"})
        second = self.store.emit({"type": "second"})
        reopened = Store(self.store.root)
        self.assertEqual([second], reopened.events(first["id"]))
        self.assertEqual([], reopened.events(second["id"]))

    def test_api_read_boundaries(self):
        self.store.emit({"type": "test"})
        api = server(self.store, 0)
        thread = threading.Thread(target=api.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{api.server_port}"
        try:
            self.assertEqual(api.server_address[0], "127.0.0.1")
            with urlopen(base + "/events?after=0&limit=1") as response:
                self.assertEqual(json.load(response)["next_after"], 1)
            for endpoint, expected in (("/events?limit=0", 400), ("/events?after=x", 400),
                                       ("/events?after=-1", 400), ("/voiceprints.json", 404), ("/audio", 404)):
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + endpoint)
                self.assertEqual(error.exception.code, expected)
        finally:
            api.shutdown()
            api.server_close()
            thread.join()

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_file_pipeline_and_tentative_models(self):
        source = self.root / "input.wav"
        write_wav(source, signal())
        fake = lambda _: {"text": "Synthetic fixture", "segments": [
            {"avg_logprob": -0.1, "no_speech_prob": 0.01}], "verified": False}
        event = process(self.store, source, transcriber=fake,
                        speaker_matcher=lambda _: {"label": "unknown", "verified": False})
        self.assertEqual(event["transcription"]["status"], "unverified")
        self.assertFalse(event["transcription"]["verified"])
        for path in event["audio"].values():
            self.assertGreater(len(read_wav(self.store.root / path)), 0)
        self.assertEqual(event["speaker"]["label"], "unknown")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_silence_never_calls_models(self):
        source = self.root / "silence.wav"
        write_wav(source, bytes(RATE * 4))
        def forbidden(_):
            self.fail("Silence should not invoke an ML model")
        event = process(self.store, source, forbidden, speaker_matcher=forbidden)
        self.assertEqual(event["transcription"]["status"], "skipped_no_speech_candidate")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_interference_gate(self):
        source = self.root / "sustained.wav"
        write_wav(source, signal(13))
        event = process(self.store, source, lambda _: self.fail("Sustained signal should skip STT"))
        self.assertEqual(event["transcription"]["status"], "skipped_sustained_signal")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_stt_failure_retains_audio_and_event(self):
        source = self.root / "input.wav"
        write_wav(source, signal())
        def fail(_):
            raise RuntimeError("simulated failure")
        event = process(self.store, source, fail)
        self.assertEqual(event["transcription"]["status"], "error")
        self.assertTrue((self.store.root / event["audio"]["raw"]).exists())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_pitch_preserves_approximate_duration(self):
        source, target = self.root / "in.wav", self.root / "out.wav"
        write_wav(source, signal(3))
        effect(source, target, 3)
        with wave.open(str(target)) as out:
            self.assertAlmostEqual(out.getnframes()/out.getframerate(), 3, delta=0.15)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_continuous_capture_tail_and_processing_error(self):
        consumed = []
        def consumer(path, timestamp):
            consumed.append(path)
            raise RuntimeError("Simulated worker failure must not erase capture")
        with patch("frs_bridge.capture.input_args", return_value=["-f", "lavfi", "-i", "sine=frequency=440:duration=11"]):
            capture(self.store, "unused", "unused", 5, consumer)
        rows = self.store.events()
        saved = [r for r in rows if r["type"] == "capture.saved"]
        self.assertEqual([r["duration_seconds"] for r in saved], [5, 5, 1])
        self.assertEqual(len(consumed), 3)
        self.assertEqual(len([r for r in rows if r["type"] == "processing.error"]), 3)
        self.assertTrue(all((self.store.root / r["recording"]).exists() for r in saved))


class VoiceprintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = Registry(self.temp.name)
        self.encoder = lambda path: {"a": [1, 0, 0], "b": [0, 1, 0], "unknown": [0, 0, 1],
                                     "ambiguous": [0.71, 0.70, 0]}[path]

    def tearDown(self):
        self.temp.cleanup()

    def test_empty_registry_is_unknown(self):
        self.assertEqual(self.registry.match("a", self.encoder)["reason"], "no_enrollments")

    def test_known_unknown_and_delete(self):
        self.registry.enroll("operator_a", ["a", "a"], self.encoder)
        self.registry.enroll("operator_b", ["b", "b"], self.encoder)
        self.assertEqual(self.registry.match("a", self.encoder)["label"], "operator_a")
        self.assertEqual(self.registry.match("unknown", self.encoder)["label"], "unknown")
        self.assertTrue(self.registry.delete("operator_a"))
        self.assertEqual(self.registry.match("a", self.encoder)["label"], "unknown")

    def test_ambiguous_rejected_even_above_threshold(self):
        self.registry.enroll("a", ["a", "a"], self.encoder)
        self.registry.enroll("b", ["b", "b"], self.encoder)
        self.assertEqual(self.registry.match("ambiguous", self.encoder, threshold=0.6)["label"], "unknown")

    def test_enrollment_validation(self):
        with self.assertRaises(ValueError):
            self.registry.enroll("../bad", ["a", "a"], self.encoder)
        with self.assertRaises(ValueError):
            self.registry.enroll("valid", ["a"], self.encoder)

    def test_threshold_validation(self):
        with self.assertRaises(ValueError):
            self.registry.match("a", self.encoder, threshold=1.5)


if __name__ == "__main__":
    unittest.main()
