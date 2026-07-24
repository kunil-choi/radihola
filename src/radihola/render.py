"""Cut a segment of the source video into a vertical (9:16) shorts clip.

Style: the original 16:9 frame is scaled to fill the 1080x1920 canvas as a
blurred background, with the un-cropped frame centered on top (so nothing in
the original picture is lost), plus a thumbnail-text banner burned in for the
first few seconds.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import youtube

DEFAULT_FONT = os.environ.get(
    "RADIHOLA_FONT", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
)
CANVAS_W = 1080
CANVAS_H = 1920
BANNER_SECONDS = 4.0


def escape_drawtext(text: str) -> str:
    """Escape a string for safe use inside an ffmpeg drawtext filter argument."""
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "’")  # avoid unbalanced quotes inside the filter
    text = text.replace("%", "\\%")
    text = text.replace("\n", " ")
    return text


@dataclass
class RenderResult:
    output_path: Path


def build_filter_complex(
    offset: float, duration: float, thumbnail_text: str, font_path: str = DEFAULT_FONT
) -> tuple[str, str, str]:
    """Return (filter_complex, video_map_label, audio_map_label)."""
    end = offset + duration
    escaped_text = escape_drawtext(thumbnail_text)
    filter_complex = (
        f"[0:v]trim=start={offset}:end={end},setpts=PTS-STARTPTS,"
        f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{CANVAS_H},gblur=sigma=20[bg];"
        f"[0:v]trim=start={offset}:end={end},setpts=PTS-STARTPTS,"
        f"scale={CANVAS_W}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
        f"[base]drawtext=fontfile={font_path}:text='{escaped_text}':"
        f"fontcolor=white:fontsize=66:line_spacing=8:"
        f"box=1:boxcolor=black@0.55:boxborderw=24:"
        f"x=(w-text_w)/2:y=140:enable='lt(t,{BANNER_SECONDS})'[vout];"
        f"[0:a]atrim=start={offset}:end={end},asetpts=PTS-STARTPTS[aout]"
    )
    return filter_complex, "[vout]", "[aout]"


def render_short(
    video_id: str,
    start_sec: float,
    end_sec: float,
    thumbnail_text: str,
    out_path: Path,
    work_dir: Path,
    pad_sec: float = 1.5,
    font_path: str = DEFAULT_FONT,
) -> RenderResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    segment_path = work_dir / f"{video_id}_segment.mp4"
    youtube.download_segment(video_id, start_sec, end_sec, segment_path, pad_sec=pad_sec)

    pad_start = max(0.0, start_sec - pad_sec)
    offset = start_sec - pad_start
    duration = end_sec - start_sec

    filter_complex, v_label, a_label = build_filter_complex(
        offset, duration, thumbnail_text, font_path=font_path
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
