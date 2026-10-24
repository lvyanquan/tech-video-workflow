import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_timeline as timing
import inspect_media as media


def make_wav(path, samples=24000, rate=24000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\0\0" * samples)


class TimelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "story.json"
        make_wav(self.root / "audio" / "intro.wav")
        self.data = {
            "schemaVersion": 1, "edition": "test-r1", "contentBaseline": "full-v1",
            "fps": 30, "width": 1920, "height": 1080,
            "minSeconds": None, "maxSeconds": None,
            "scenes": [{
                "id": "intro", "title": "开场", "headFrames": 3, "tailFrames": 6,
                "audio": "audio/intro.wav",
                "displayText": "介绍 3.7.0。", "spokenText": "介绍三点七点零。",
                "captions": [{"text": "介绍 3.7.0。", "startMs": 100, "endMs": 900}],
                "cues": [{"id": "version", "atMs": 500}],
            }],
        }

    def save(self):
        self.manifest.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")

    def build(self):
        self.save()
        return timing.build(self.manifest)

    def test_sample_timing_and_display_speech_separation(self):
        timeline, caps = self.build()
        scene = timeline["scenes"][0]
        self.assertEqual(timeline["totalFrames"], 39)
        self.assertEqual(scene["audioFrames"], 30)
        self.assertEqual(scene["globalAudioFromFrame"], 3)
        self.assertEqual(scene["cues"][0]["frame"], 18)
        self.assertEqual((caps[0]["startMs"], caps[0]["endMs"]), (200, 1000))
        self.assertEqual(caps[0]["text"], "介绍 3.7.0。")
        self.assertEqual(scene["spokenText"], "介绍三点七点零。")
        self.assertEqual(len(scene["audioSha256"]), 64)

    def test_second_scene_uses_one_global_offset(self):
        scene = copy.deepcopy(self.data["scenes"][0])
        scene["id"] = "next"
        self.data["scenes"].append(scene)
        timeline, caps = self.build()
        self.assertEqual(timeline["scenes"][1]["from"], 39)
        self.assertEqual(timeline["totalFrames"], 78)
        self.assertEqual(caps[1]["startMs"], 1500)
        self.assertEqual(timeline["scenes"][1]["captions"][0]["startMs"], 200)

    def test_fractional_audio_length_rounds_up_not_down(self):
        make_wav(self.root / "audio/intro.wav", samples=24001)
        timeline, _ = self.build()
        self.assertEqual(timeline["scenes"][0]["audioFrames"], 31)
        self.assertEqual(timeline["totalFrames"], 40)

    def test_output_has_srt_and_chapters_and_no_spoken_alias(self):
        self.save()
        out = self.root / "timing-r1"
        timing.write_outputs(self.manifest, out)
        self.assertEqual(
            {p.name for p in out.iterdir()},
            {"timeline.json", "captions.json", "captions.srt", "chapters.txt"},
        )
        srt = (out / "captions.srt").read_text()
        self.assertIn("00:00:00,200 --> 00:00:01,000", srt)
        self.assertIn("3.7.0", srt)
        self.assertNotIn("三点七点零", srt)
        self.assertIn("00:00:00.000 开场", (out / "chapters.txt").read_text())

    def test_existing_output_is_preserved(self):
        self.save()
        out = self.root / "existing"
        out.mkdir()
        (out / "keep").write_text("unchanged")
        with self.assertRaises(FileExistsError):
            timing.write_outputs(self.manifest, out)
        self.assertEqual((out / "keep").read_text(), "unchanged")

    def test_invalid_input_creates_no_output(self):
        self.data["scenes"][0]["captions"][0]["endMs"] = 1001
        self.save()
        out = self.root / "bad"
        with self.assertRaises(ValueError):
            timing.write_outputs(self.manifest, out)
        self.assertFalse(out.exists())

    def test_duplicate_scene_is_rejected(self):
        self.data["scenes"].append(copy.deepcopy(self.data["scenes"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate scene"):
            self.build()

    def test_caption_overlap_or_unsorted_is_rejected(self):
        self.data["scenes"][0]["captions"].append(
            {"text": "重复", "startMs": 800, "endMs": 950}
        )
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.build()

    def test_caption_bounds_and_numeric_types(self):
        for start, end in [(-1, 900), (900, 900), (100, 1001), (True, 900), (0.5, 900)]:
            with self.subTest(start=start, end=end):
                self.data["scenes"][0]["captions"][0].update(startMs=start, endMs=end)
                with self.assertRaises(ValueError):
                    self.build()

    def test_different_display_text_is_rejected(self):
        self.data["scenes"][0]["displayText"] = "介绍 3.8.0。"
        with self.assertRaisesRegex(ValueError, "displayText"):
            self.build()

    def test_whitespace_can_differ_but_punctuation_cannot(self):
        self.data["scenes"][0]["captions"][0]["text"] = "介绍\n3.7.0。"
        self.build()
        self.data["scenes"][0]["captions"][0]["text"] = "介绍 3.7.0！"
        with self.assertRaises(ValueError):
            self.build()

    def test_cues_must_be_unique_ordered_and_inside_audio(self):
        for cues in [
            [{"id": "x", "atMs": 1000}],
            [{"id": "x", "atMs": 500}, {"id": "y", "atMs": 200}],
            [{"id": "x", "atMs": 200}, {"id": "x", "atMs": 500}],
        ]:
            with self.subTest(cues=cues):
                self.data["scenes"][0]["cues"] = cues
                with self.assertRaises(ValueError):
                    self.build()

    def test_cue_rounding_stays_inside_final_audio_frame(self):
        self.data["scenes"][0]["cues"][0]["atMs"] = 999
        timeline, _ = self.build()
        self.assertEqual(timeline["scenes"][0]["cues"][0]["frame"], 32)

    def test_duration_limits(self):
        self.data["minSeconds"] = 1.3
        self.data["maxSeconds"] = 1.31
        self.build()
        self.data["maxSeconds"] = 1.3
        with self.assertRaisesRegex(ValueError, "maxSeconds"):
            self.build()
        self.data["maxSeconds"] = None
        self.data["minSeconds"] = 1.31
        with self.assertRaisesRegex(ValueError, "minSeconds"):
            self.build()

    def test_nonfinite_and_negative_limits(self):
        for value in [float("nan"), float("inf"), -1, 0, True, "300"]:
            with self.subTest(value=value):
                self.data["maxSeconds"] = value
                with self.assertRaises(ValueError):
                    self.build()

    def test_invalid_fps_and_empty_scenes(self):
        for value in [0, -1, 29.97, True]:
            self.data["fps"] = value
            with self.assertRaises(ValueError):
                self.build()
        self.data["fps"] = 30
        self.data["scenes"] = []
        with self.assertRaises(ValueError):
            self.build()

    def test_paths_cannot_escape_or_use_network(self):
        for path in ["../outside.wav", "/tmp/out.wav", "https://example.com/a.wav",
                     ".secrets/key.wav", "audio\\intro.wav", "missing.wav"]:
            with self.subTest(path=path):
                self.data["scenes"][0]["audio"] = path
                with self.assertRaises(ValueError):
                    self.build()

    def test_symlink_audio_and_parent_rejected(self):
        (self.root / "alias.wav").symlink_to(self.root / "audio/intro.wav")
        self.data["scenes"][0]["audio"] = "alias.wav"
        with self.assertRaises(ValueError):
            self.build()
        (self.root / "alias").symlink_to(self.root / "audio", target_is_directory=True)
        self.data["scenes"][0]["audio"] = "alias/intro.wav"
        with self.assertRaises(ValueError):
            self.build()

    def test_truncated_wav_rejected(self):
        path = self.root / "audio/intro.wav"
        path.write_bytes(path.read_bytes()[:-8])
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.build()

    def test_audio_hash_changes_after_audio_changes(self):
        first, _ = self.build()
        make_wav(self.root / "audio/intro.wav", samples=30000)
        second, _ = self.build()
        self.assertNotEqual(
            first["scenes"][0]["audioSha256"], second["scenes"][0]["audioSha256"]
        )
        self.assertGreater(second["totalFrames"], first["totalFrames"])

    def test_cli_failure_is_nonzero(self):
        self.save()
        result = subprocess.run(
            [sys.executable, str(Path(timing.__file__)), "--manifest",
             str(self.manifest), "--output", str(self.root)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timeline not built", result.stderr)


class MediaValidationTest(unittest.TestCase):
    def setUp(self):
        self.timeline = {
            "fps": 30, "totalFrames": 60, "width": 640, "height": 360,
            "durationSeconds": 2.0, "minSeconds": None, "maxSeconds": None,
        }
        self.probe = {
            "format": {"duration": "2.0"},
            "streams": [
                {"codec_type": "video", "width": 640, "height": 360,
                 "avg_frame_rate": "30/1", "nb_read_frames": "60",
                 "duration": "2.0", "start_time": "0.0"},
                {"codec_type": "audio", "duration": "2.0", "start_time": "0.0"},
            ],
        }

    def test_valid_metadata(self):
        summary = media.validate_probe(self.probe, self.timeline, "required")
        self.assertEqual(summary["decodedFrames"], 60)
        self.assertEqual(summary["audioStreams"], 1)

    def test_invalid_document_types_and_audio_mode(self):
        for probe, timeline, mode in [
            ([], self.timeline, "required"),
            (self.probe, [], "required"),
            (self.probe, self.timeline, "typo"),
        ]:
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    media.validate_probe(probe, timeline, mode)

    def test_audio_modes(self):
        with self.assertRaises(ValueError):
            media.validate_probe(self.probe, self.timeline, "absent")
        self.probe["streams"].pop()
        with self.assertRaises(ValueError):
            media.validate_probe(self.probe, self.timeline, "required")
        media.validate_probe(self.probe, self.timeline, "optional")
        media.validate_probe(self.probe, self.timeline, "absent")

    def test_wrong_frame_count_dimensions_or_fps(self):
        for key, value in [("nb_read_frames", "59"), ("width", 1920),
                           ("avg_frame_rate", "25/1")]:
            with self.subTest(key=key):
                probe = copy.deepcopy(self.probe)
                probe["streams"][0][key] = value
                with self.assertRaises(ValueError):
                    media.validate_probe(probe, self.timeline, "required")

    def test_audio_truncated_or_delayed(self):
        for key, value in [("duration", "1.2"), ("start_time", "0.5")]:
            probe = copy.deepcopy(self.probe)
            probe["streams"][1][key] = value
            with self.assertRaises(ValueError):
                media.validate_probe(probe, self.timeline, "required")

    def test_timeline_contradiction(self):
        self.timeline["durationSeconds"] = 4
        with self.assertRaises(ValueError):
            media.validate_probe(self.probe, self.timeline, "required")

    def test_strict_max_checks_container_not_just_frame_duration(self):
        self.timeline["maxSeconds"] = 2.01
        self.probe["format"]["duration"] = "2.02"
        with self.assertRaisesRegex(ValueError, "maximum"):
            media.validate_probe(self.probe, self.timeline, "required")

    def test_nonfinite_or_missing_stream_timing(self):
        self.probe["streams"][1]["duration"] = "NaN"
        with self.assertRaises(ValueError):
            media.validate_probe(self.probe, self.timeline, "required")
        del self.probe["streams"][1]["duration"]
        with self.assertRaises(ValueError):
            media.validate_probe(self.probe, self.timeline, "required")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe unavailable")
class MediaIntegrationTest(unittest.TestCase):
    def test_real_encoding_probe_and_full_decode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / "short.mp4"
            timeline = root / "timeline.json"
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                "color=c=navy:s=320x180:r=30:d=1", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video),
            ], check=True, capture_output=True)
            timeline.write_text(json.dumps({
                "edition": "integration-r1", "fps": 30, "width": 320, "height": 180,
                "totalFrames": 30, "durationSeconds": 1.0,
            }))
            result = media.inspect(video, timeline)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["fullDecode"])
            self.assertIn("pronunciation and listening quality", result["notChecked"])


if __name__ == "__main__":
    unittest.main()
