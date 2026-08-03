"""Cut a segment of the source video into a vertical (9:16) shorts clip.

Style (matches the reference https://www.youtube.com/shorts/-xAF_GxDIBU):
  - a black title band across the top, up to two lines of bold text (first
    line white, second line gold) taken from ``thumbnail_text`` split on a
    newline
  - the source video center-cropped to fill the rest of the canvas edge to
    edge (no letterboxing/blur - matches the reference's full-bleed video)
  - small station/show wordmarks overlaid top-left / top-right of the video
    (text placeholders until real logo image files are supplied - see
    ``LOGO_LEFT_TEXT``/``LOGO_RIGHT_TEXT``)
  - burned-in captions at the bottom, synced to the transcript segments that
    fall within the clip, styled as bold white-on-black like the reference
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import youtube
from .transcript import Segment

DEFAULT_FONT = os.environ.get(
    "RADIHOLA_FONT", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
)
CANVAS_W = 1080
CANVAS_H = 1920

TITLE_BAND_H = 300
TITLE_LINE1_Y = 70
TITLE_LINE2_Y = 168
TITLE_FONTSIZE = 62

# text placeholders for the top-left/top-right logos, used until real logo
# image files are added (see module docstring)
LOGO_LEFT_TEXT = "KBS 1 Radio"
LOGO_RIGHT_TEXT = "라디올리"
LOGO_FONTSIZE = 34
LOGO_MARGIN_X = 40
LOGO_MARGIN_Y = 26

CAPTION_FONTSIZE = 52
CAPTION_MARGIN_BOTTOM = 260
CAPTION_MAX_CHARS_PER_LINE = 16


def escape_drawtext(text: str, keep_newlines: bool = False) -> str:
    """Escape a string for safe use inside an ffmpeg drawtext filter argument."""
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "’")  # avoid unbalanced quotes inside the filter
    text = text.replace("%", "\\%")
    if not keep_newlines:
        text = text.replace("\n", " ")
    return text


def _title_lines(thumbnail_text: str) -> tuple[str, str | None]:
    """Split thumbnail_text into (line1, line2). line2 is None if not given."""
    parts = thumbnail_text.split("\n", 1)
    line1 = parts[0].strip()
    line2 = parts[1].strip() if len(parts) > 1 else None
    return line1, (line2 or None)


def _wrap_caption(text: str, max_chars: int = CAPTION_MAX_CHARS_PER_LINE) -> str:
    """Wrap caption text onto at most 2 lines, breaking near the midpoint on a space."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    mid = len(text) // 2
    # search outward from the midpoint for a space to break on
    break_at = None
    for offset in range(0, mid + 1):
        for candidate in (mid - offset, mid + offset):
            if 0 < candidate < len(text) and text[candidate] == " ":
                break_at = candidate
                break
        if break_at is not None:
            break
    if break_at is None:
        return text
    return text[:break_at] + "\n" + text[break_at + 1 :]


def _relative_captions(
    segments: list[Segment], start_sec: float, end_sec: float
) -> list[tuple[float, float, str]]:
    """Segments overlapping [start_sec, end_sec], with times relative to start_sec."""
    out = []
    for seg in segments:
        if seg.end_sec <= start_sec or seg.start_sec >= end_sec:
            continue
        rel_start = max(0.0, seg.start_sec - start_sec)
        rel_end = min(end_sec - start_sec, seg.end_sec - start_sec)
        if rel_end <= rel_start:
            continue
        out.append((rel_start, rel_end, seg.text))
    return out


@dataclass
class RenderResult:
    output_path: Path


def build_filter_complex(
    offset: float,
    duration: float,
    thumbnail_text: str,
    captions: list[tuple[float, float, str]] | None = None,
    font_path: str = DEFAULT_FONT,
    logo_left_text: str | None = LOGO_LEFT_TEXT,
    logo_right_text: str | None = LOGO_RIGHT_TEXT,
) -> tuple[str, str, str]:
    """Return (filter_complex, video_map_label, audio_map_label)."""
    end = offset + duration
    captions = captions or []
    video_h = CANVAS_H - TITLE_BAND_H

    stages = [
        f"[0:v]trim=start={offset}:end={end},setpts=PTS-STARTPTS,"
        f"scale={CANVAS_W}:{video_h}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{video_h}[cropped]",
        f"[cropped]pad={CANVAS_W}:{CANVAS_H}:0:{TITLE_BAND_H}:color=black[padded]",
    ]

    line1, line2 = _title_lines(thumbnail_text)
    last = "padded"
    stages.append(
        f"[{last}]drawtext=fontfile={font_path}:text='{escape_drawtext(line1)}':"
        f"fontcolor=white:fontsize={TITLE_FONTSIZE}:"
        f"x=(w-text_w)/2:y={TITLE_LINE1_Y}[t1]"
    )
    last = "t1"
    if line2:
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:text='{escape_drawtext(line2)}':"
            f"fontcolor=gold:fontsize={TITLE_FONTSIZE}:"
            f"x=(w-text_w)/2:y={TITLE_LINE2_Y}[t2]"
        )
        last = "t2"

    if logo_left_text:
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:text='{escape_drawtext(logo_left_text)}':"
            f"fontcolor=white:fontsize={LOGO_FONTSIZE}:"
            f"x={LOGO_MARGIN_X}:y={TITLE_BAND_H + LOGO_MARGIN_Y}[lg1]"
        )
        last = "lg1"
    if logo_right_text:
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:text='{escape_drawtext(logo_right_text)}':"
            f"fontcolor=white:fontsize={LOGO_FONTSIZE}:"
            f"x=w-text_w-{LOGO_MARGIN_X}:y={TITLE_BAND_H + LOGO_MARGIN_Y}[lg2]"
        )
        last = "lg2"

    for i, (cue_start, cue_end, text) in enumerate(captions):
        wrapped = _wrap_caption(text)
        label = f"cap{i}"
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:text='{escape_drawtext(wrapped, keep_newlines=True)}':"
            f"fontcolor=white:fontsize={CAPTION_FONTSIZE}:line_spacing=6:"
            f"box=1:boxcolor=black@0.6:boxborderw=20:"
            f"x=(w-text_w)/2:y=h-{CAPTION_MARGIN_BOTTOM}:"
            f"enable='between(t,{cue_start},{cue_end})'[{label}]"
        )
        last = label

    stages.append(f"[{last}]null[vout]")
    stages.append(f"[0:a]atrim=start={offset}:end={end},asetpts=PTS-STARTPTS[aout]")

    return ";".join(stages), "[vout]", "[aout]"


def render_short(
    video_id: str,
    start_sec: float,
    end_sec: float,
    thumbnail_text: str,
    out_path: Path,
    work_dir: Path,
    pad_sec: float = 1.5,
    font_path: str = DEFAULT_FONT,
    segments: list[Segment] | None = None,
) -> RenderResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    segment_path = work_dir / f"{video_id}_segment.mp4"
    youtube.download_segment(video_id, start_sec, end_sec, segment_path, pad_sec=pad_sec)

    pad_start = max(0.0, start_sec - pad_sec)
    offset = start_sec - pad_start
    duration = end_sec - start_sec

    captions = _relative_captions(segments or [], start_sec, end_sec)

    filter_complex, v_label, a_label = build_filter_complex(
        offset, duration, thumbnail_text, captions=captions, font_path=font_path
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(segment_path),
        "-filter_complex",
        filter_complex,
        "-map",
        v_label,
        "-map",
        a_label,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    return RenderResult(output_path=out_path)
