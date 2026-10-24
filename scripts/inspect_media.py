"""Inspect a local MP4 against a timeline and fully decode its AV streams."""

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess

from build_timeline import digest, integer


def validate_probe(probe, timeline, audio_mode):
    if not isinstance(probe, dict) or not isinstance(timeline, dict):
        raise ValueError("probe and timeline must be JSON objects")
    if audio_mode not in {"required", "optional", "absent"}:
        raise ValueError("invalid audio mode")
    fps = integer(timeline.get("fps"), "fps", 1)
    frames = integer(timeline.get("totalFrames"), "totalFrames", 1)
    width = integer(timeline.get("width"), "width", 1)
    height = integer(timeline.get("height"), "height", 1)
    seconds = frames / fps
    declared = timeline.get("durationSeconds")
    if type(declared) not in (int, float) or not math.isfinite(declared):
        raise ValueError("timeline durationSeconds must be finite")
    if abs(declared - seconds) > 1e-6:
        raise ValueError("timeline durationSeconds contradicts frame count")
    streams = probe.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if len(video) != 1:
        raise ValueError("expected exactly one video stream")
    if audio_mode == "required" and not audio:
        raise ValueError("audio stream is missing")
    if audio_mode == "absent" and audio:
        raise ValueError("expected no audio stream")
    v = video[0]
    if (v.get("width"), v.get("height")) != (width, height):
        raise ValueError("video dimensions differ from timeline")
    try:
        if abs(float(Fraction(v["avg_frame_rate"])) - fps) > 0.001:
            raise ValueError("video frame rate differs from timeline")
        if int(v["nb_read_frames"]) != frames:
            raise ValueError("decoded video frame count differs from timeline")
        container_duration = float(probe["format"]["duration"])
    except (KeyError, ZeroDivisionError, TypeError) as exc:
        raise ValueError("missing or invalid probe frame/duration data") from exc
    tolerance = max(0.1, 2 / fps)
    if not math.isfinite(container_duration) or abs(container_duration - seconds) > tolerance:
        raise ValueError("container duration differs from timeline")
    for stream in [v, *audio]:
        try:
            duration = float(stream["duration"])
            start = float(stream["start_time"])
        except (KeyError, TypeError) as exc:
            raise ValueError("stream timing missing; verify manually") from exc
        if not all(map(math.isfinite, (duration, start))):
            raise ValueError("nonfinite stream timing")
        if abs(start) > tolerance or abs(start + duration - seconds) > tolerance:
            raise ValueError("audio/video stream does not span the expected timeline")
    for key in ("minSeconds", "maxSeconds"):
        bound = timeline.get(key)
        if bound is None:
            continue
        if type(bound) not in (int, float) or not math.isfinite(bound) or bound <= 0:
            raise ValueError(f"invalid {key}")
        if key == "minSeconds" and container_duration < bound:
            raise ValueError("final container is below minimum duration")
        if key == "maxSeconds" and container_duration >= bound:
            raise ValueError("final container violates strict maximum duration")
    return {
        "width": width, "height": height, "fps": fps, "decodedFrames": frames,
        "durationSeconds": container_duration, "audioStreams": len(audio),
    }


def run(command):
    completed = subprocess.run(command, text=True, capture_output=True, check=True)
    if completed.stderr.strip():
        raise ValueError("media tool reported errors: " + completed.stderr[:1500])
    return completed.stdout


def inspect(video, timeline_path, audio_mode="required", ffprobe="ffprobe", ffmpeg="ffmpeg"):
    video = Path(video).resolve()
    if not video.is_file() or video.suffix.lower() != ".mp4":
        raise ValueError("video must be an existing local .mp4 file")
    timeline = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
    probe = json.loads(run([
        ffprobe, "-v", "error", "-count_frames", "-show_streams", "-show_format",
        "-of", "json", str(video),
    ]))
    summary = validate_probe(probe, timeline, audio_mode)
    run([
        ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", str(video),
        "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-",
    ])
    return {
        "status": "PASS", "file": video.name, "sha256": digest(video),
        "edition": timeline.get("edition"), "media": summary,
        "fullDecode": True,
        "notChecked": [
            "visual quality and on-screen logos", "pronunciation and listening quality",
            "semantic caption/audio alignment", "loudness and music balance",
            "technical facts and source permissions",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--audio", choices=("required", "optional", "absent"), default="required")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    try:
        result = inspect(args.video, args.timeline, args.audio, args.ffprobe, args.ffmpeg)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Media verification failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
