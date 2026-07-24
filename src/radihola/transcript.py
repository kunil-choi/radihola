"""Turn a video into a timestamped transcript.

Prefers YouTube's own captions (manual or auto-generated); falls back to
local speech-to-text with faster-whisper when no captions are available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import webvtt

from . import youtube


@dataclass
class Segment:
    start_sec: float
    end_sec: float
    text: str


def _vtt_timestamp_to_sec(ts: str) -> float:
    # "HH:MM:SS.mmm" or "MM:SS.mmm"
    parts = ts.split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def parse_vtt(vtt_path: Path) -> list[Segment]:
    """Parse a vtt file into segments, collapsing YouTube's rolling-caption
    duplication (auto captions repeat trailing words across consecutive cues).
    """
    segments: list[Segment] = []
    last_text = ""
    for caption in webvtt.read(str(vtt_path)):
        text = re.sub(r"<[^>]+>", "", caption.text).strip()
        text = " ".join(line.strip() for line in text.splitlines() if line.strip())
        if not text or text == last_text:
            continue
        # auto captions often prefix the previous cue's tail; drop the overlap
        if last_text and text.startswith(last_text):
            text = text[len(last_text):].strip()
        if not text:
            continue
        start = _vtt_timestamp_to_sec(caption.start)
        end = _vtt_timestamp_to_sec(caption.end)
        segments.append(Segment(start_sec=start, end_sec=end, text=text))
        last_text = re.sub(r"<[^>]+>", "", caption.text).strip().splitlines()[-1].strip()
    return segments


def get_transcript(video_id: str, work_dir: Path, lang: str = "ko") -> tuple[list[Segment], str]:
    """Return (segments, source) where source is 'youtube_captions' or 'whisper'."""
    vtt_path = youtube.download_auto_captions(video_id, work_dir, lang=lang)
    if vtt_path is not None:
        segments = parse_vtt(vtt_path)
        if segments:
            return segments, "youtube_captions"

    audio_path = youtube.download_audio(video_id, work_dir)
    segments = whisper_transcribe(audio_path, lang=lang)
    return segments, "whisper"


def whisper_transcribe(audio_path: Path, lang: str = "ko", model_size: str = "small") -> list[Segment]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    raw_segments, _info = model.transcribe(str(audio_path), language=lang, vad_filter=True)
    return [
        Segment(start_sec=s.start, end_sec=s.end, text=s.text.strip())
        for s in raw_segments
        if s.text.strip()
    ]


def format_for_prompt(segments: list[Segment]) -> str:
    """Render segments as "[mm:ss-mm:ss] text" lines for the analysis prompt."""

    def hms(sec: float) -> str:
        m, s = divmod(int(sec), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    return "\n".join(f"[{hms(s.start_sec)}-{hms(s.end_sec)}] {s.text}" for s in segments)
