"""Build a frame timeline and captions from local PCM WAV and aligned text."""

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import wave


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def identifier(value, name):
    text(value, name)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise ValueError(f"{name} must use letters, digits, underscores or hyphens")
    return value


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def local_audio(root, value):
    value = text(value, "audio")
    rel = PurePosixPath(value)
    if rel.is_absolute() or "\\" in value or ":" in value:
        raise ValueError("audio must be a local relative POSIX path")
    if any(part in {".", ".."} or part.startswith(".") for part in rel.parts):
        raise ValueError("audio path traversal and hidden paths are not allowed")
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("audio symlinks are not allowed")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError(f"audio must exist inside the manifest directory: {value}")
    if path.suffix.lower() != ".wav":
        raise ValueError("convert audio to PCM WAV before building the timeline")
    return path


def wav_info(path):
    with wave.open(str(path), "rb") as audio:
        if audio.getcomptype() != "NONE":
            raise ValueError("only uncompressed PCM WAV is supported")
        samples = audio.getnframes()
        rate = audio.getframerate()
        if samples <= 0 or rate <= 0:
            raise ValueError("audio must contain samples")
        expected = samples * audio.getnchannels() * audio.getsampwidth()
        actual = 0
        for block in iter(lambda: audio.readframes(65536), b""):
            actual += len(block)
        if actual != expected:
            raise ValueError("truncated WAV sample data")
    return samples, rate


def timestamp(ms, separator=","):
    return (
        f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:"
        f"{ms // 1000 % 60:02d}{separator}{ms % 1000:03d}"
    )


def build(manifest):
    manifest = Path(manifest).resolve()
    source = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(source, dict) or type(source.get("schemaVersion")) is not int:
        raise ValueError("schemaVersion must be 1")
    if source["schemaVersion"] != 1:
        raise ValueError("unsupported schemaVersion")
    fps = integer(source.get("fps"), "fps", 1)
    width = integer(source.get("width"), "width", 1)
    height = integer(source.get("height"), "height", 1)
    edition = identifier(source.get("edition"), "edition")
    baseline = text(source.get("contentBaseline"), "contentBaseline")
    scenes = source.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("scenes must be a nonempty list")
    cursor, result, captions, seen = 0, [], [], set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("each scene must be an object")
        sid = identifier(scene.get("id"), "scene id")
        if sid in seen:
            raise ValueError(f"duplicate scene id: {sid}")
        seen.add(sid)
        title = text(scene.get("title"), "title")
        if "\n" in title or "\r" in title:
            raise ValueError("title must be a single line")
        display = text(scene.get("displayText"), "displayText")
        spoken = text(scene.get("spokenText"), "spokenText")
        head = integer(scene.get("headFrames", 0), "headFrames")
        tail = integer(scene.get("tailFrames", 0), "tailFrames")
        audio = local_audio(manifest.parent, scene.get("audio"))
        samples, rate = wav_info(audio)
        audio_ms = Fraction(samples * 1000, rate)
        audio_frames = (samples * fps + rate - 1) // rate
        duration = head + audio_frames + tail
        raw_caps = scene.get("captions")
        if not isinstance(raw_caps, list) or not raw_caps:
            raise ValueError(f"{sid}: aligned captions are required")
        previous_end, local_caps = 0, []
        for cap in raw_caps:
            if not isinstance(cap, dict):
                raise ValueError("caption must be an object")
            body = text(cap.get("text"), "caption text")
            if "\n\n" in body or "\r" in body:
                raise ValueError("caption text cannot contain blank lines or CR")
            start = integer(cap.get("startMs"), "startMs")
            end = integer(cap.get("endMs"), "endMs", 1)
            if not previous_end <= start < end <= audio_ms:
                raise ValueError(f"{sid}: caption overlap, order or audio bounds error")
            previous_end = end
            local = {
                "text": body,
                "startMs": round(Fraction(head * 1000, fps) + start),
                "endMs": round(Fraction(head * 1000, fps) + end),
                "timestampMs": None,
                "confidence": None,
            }
            local_caps.append(local)
            captions.append({
                **local,
                "startMs": round(Fraction((cursor + head) * 1000, fps) + start),
                "endMs": round(Fraction((cursor + head) * 1000, fps) + end),
            })
        normalize = lambda value: "".join(value.split())
        if normalize("".join(c["text"] for c in raw_caps)) != normalize(display):
            raise ValueError(f"{sid}: captions differ from displayText (except whitespace)")
        raw_cues = scene.get("cues", [])
        if not isinstance(raw_cues, list):
            raise ValueError("cues must be a list")
        cues, cue_ids, previous_cue = [], set(), -1
        for cue in raw_cues:
            if not isinstance(cue, dict):
                raise ValueError("cue must be an object")
            cid = identifier(cue.get("id"), "cue id")
            at = integer(cue.get("atMs"), "cue atMs")
            if cid in cue_ids or not previous_cue <= at < audio_ms:
                raise ValueError(f"{sid}: cue duplicate, order or audio bounds error")
            cue_ids.add(cid)
            previous_cue = at
            frame = head + min(audio_frames - 1, round(Fraction(at * fps, 1000)))
            cues.append({"id": cid, "frame": frame, "globalFrame": cursor + frame})
        result.append({
            "id": sid, "title": title, "from": cursor,
            "durationInFrames": duration, "headFrames": head, "tailFrames": tail,
            "audioFrames": audio_frames, "audioFromFrame": head,
            "globalAudioFromFrame": cursor + head,
            "audio": scene["audio"], "audioSha256": digest(audio),
            "audioSamples": samples, "sampleRate": rate,
            "audioDurationMs": float(audio_ms),
            "displayText": display, "spokenText": spoken,
            "captions": local_caps, "cues": cues,
        })
        cursor += duration
    seconds = Fraction(cursor, fps)
    limits = {}
    for key in ("minSeconds", "maxSeconds"):
        value = source.get(key)
        if value is None:
            limits[key] = None
            continue
        if type(value) not in (int, float):
            raise ValueError(f"{key} must be a positive finite number or null")
        try:
            bound = Fraction(str(value))
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"{key} must be finite") from exc
        if bound <= 0:
            raise ValueError(f"{key} must be positive")
        limits[key] = value
        if (key == "minSeconds" and seconds < bound) or (
            key == "maxSeconds" and seconds >= bound
        ):
            raise ValueError(f"duration {float(seconds):.3f}s violates {key}={value}")
    return {
        "schemaVersion": 1, "edition": edition, "contentBaseline": baseline,
        "fps": fps, "width": width, "height": height, "totalFrames": cursor,
        "durationSeconds": float(seconds), **limits,
        "audioPathBase": "input manifest directory",
        "manifestSha256": digest(manifest), "scenes": result,
    }, captions


def write_outputs(manifest, output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("output must be a new directory; do not overwrite an edition")
    timeline, captions = build(manifest)
    if not output.parent.is_dir():
        raise ValueError("output parent directory must exist")
    temp = Path(tempfile.mkdtemp(prefix=".timeline-", dir=output.parent))
    try:
        for name, data in (("timeline.json", timeline), ("captions.json", captions)):
            (temp / name).write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        (temp / "captions.srt").write_text("\n\n".join(
            f"{i}\n{timestamp(c['startMs'])} --> {timestamp(c['endMs'])}\n{c['text']}"
            for i, c in enumerate(captions, 1)
        ) + "\n", encoding="utf-8")
        (temp / "chapters.txt").write_text("".join(
            f"{timestamp(round(Fraction(s['from'] * 1000, timeline['fps'])), '.')} "
            f"{s['title']}\n" for s in timeline["scenes"]
        ), encoding="utf-8")
        # Reserve the final name only after validation; never replace an existing edition.
        output.mkdir()
        for path in temp.iterdir():
            path.rename(output / path.name)
    finally:
        shutil.rmtree(temp)
    return timeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = write_outputs(args.manifest, args.output)
    except (OSError, ValueError, wave.Error, EOFError) as exc:
        parser.exit(1, f"Timeline not built: {exc}\n")
    print(json.dumps({
        "status": "BUILT", "edition": result["edition"],
        "frames": result["totalFrames"], "seconds": result["durationSeconds"],
        "scope": "timing and text consistency only; no listening or visual review",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
