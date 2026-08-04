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
import shutil
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


def _face_crop_offset(
    faces: list[tuple[float, float, float, float]],
    scale: float,
    canvas_w: int,
    canvas_h: int,
    scaled_w: float,
    scaled_h: float,
) -> tuple[int, int] | None:
    """Given detected face boxes (x, y, w, h) in original-frame pixel coords,
    return the (x, y) crop offset - in scaled-frame pixel coords - that keeps
    the most prominent face(s) inside a canvas_w x canvas_h crop window,
    biased to leave headroom above the face rather than dead-centering it.
    None if no faces were given.
    """
    if not faces:
        return None
    total_area = 0.0
    weighted_x = 0.0
    weighted_y = 0.0
    for x, y, w, h in faces:
        area = w * h
        weighted_x += (x + w / 2) * area
        weighted_y += (y + h * 0.35) * area  # roughly eye-level, not box center
        total_area += area
    face_x = (weighted_x / total_area) * scale
    face_y = (weighted_y / total_area) * scale

    max_x_off = max(0.0, scaled_w - canvas_w)
    max_y_off = max(0.0, scaled_h - canvas_h)
    x_off = min(max(0.0, face_x - canvas_w / 2), max_x_off)
    y_off = min(max(0.0, face_y - canvas_h / 3), max_y_off)
    return round(x_off), round(y_off)


def _detect_faces(image_path: Path) -> list[tuple[float, float, float, float]]:
    """Detect faces in a single image, returning (x, y, w, h) boxes in pixel
    coords. Empty on any failure (no opencv installed, a build/version that
    dropped CascadeClassifier, unreadable image, etc.) - callers treat that
    the same as "no faces found"."""
    try:
        import cv2
    except ImportError:
        return []
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return []
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        boxes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        return [(float(x), float(y), float(w), float(h)) for x, y, w, h in boxes]
    except (AttributeError, cv2.error):
        return []


def _probe_dimensions(video_path: Path) -> tuple[int, int] | None:
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0",
                str(video_path),
            ],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        w, h = (int(v) for v in out.split(","))
        return w, h
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None


def find_speaker_crop(segment_path: Path, canvas_w: int, canvas_h: int) -> tuple[str, str]:
    """Best-effort: sample a few frames from segment_path, detect faces, and
    return (crop_x, crop_y) ffmpeg crop-filter position values that keep the
    most prominent speaker in frame instead of a blind center crop. Falls
    back to ffmpeg's own centered crop on any failure (opencv not installed,
    no faces found, ffprobe/ffmpeg failure, etc.) - never raises.
    """
    default = ("(in_w-out_w)/2", "(in_h-out_h)/2")
    try:
        import cv2  # noqa: F401
    except ImportError:
        return default

    dims = _probe_dimensions(segment_path)
    if dims is None:
        return default
    src_w, src_h = dims
    scale = max(canvas_w / src_w, canvas_h / src_h)
    scaled_w, scaled_h = src_w * scale, src_h * scale

    frames_dir = segment_path.parent / "face_sample_frames"
    frames_dir.mkdir(exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(segment_path), "-vf", "fps=1/3",
                str(frames_dir / "f_%03d.jpg"),
            ],
            check=True, capture_output=True,
        )
        all_faces: list[tuple[float, float, float, float]] = []
        for frame_path in sorted(frames_dir.glob("f_*.jpg")):
            all_faces.extend(_detect_faces(frame_path))
    except subprocess.CalledProcessError:
        return default
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)

    offset = _face_crop_offset(all_faces, scale, canvas_w, canvas_h, scaled_w, scaled_h)
    if offset is None:
        return default
    return str(offset[0]), str(offset[1])


def build_filter_complex(
    offset: float,
    duration: float,
    thumbnail_text: str,
    captions: list[tuple[float, float, str]] | None = None,
    font_path: str = DEFAULT_FONT,
    logo_left_text: str | None = LOGO_LEFT_TEXT,
    logo_right_text: str | None = LOGO_RIGHT_TEXT,
    crop_x: str = "(in_w-out_w)/2",
    crop_y: str = "(in_h-out_h)/2",
) -> tuple[str, str, str]:
    """Return (filter_complex, video_map_label, audio_map_label).

    crop_x/crop_y are ffmpeg crop-filter position expressions (or plain pixel
    offsets), in the coordinate space of the scaled frame. Defaults to a plain
    center crop; render_short() overrides them with a face-detected offset
    when possible so a speaker isn't cropped out by a blind center crop.
    """
    end = offset + duration
    captions = captions or []
    video_h = CANVAS_H - TITLE_BAND_H

    stages = [
        f"[0:v]trim=start={offset}:end={end},setpts=PTS-STARTPTS,"
        f"scale={CANVAS_W}:{video_h}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{video_h}:{crop_x}:{crop_y}[cropped]",
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

    video_h = CANVAS_H - TITLE_BAND_H
    crop_x, crop_y = find_speaker_crop(segment_path, CANVAS_W, video_h)

    # ffmpeg's filter option syntax uses ':' as a key=value separator, so a raw
    # font path containing one (e.g. a Windows drive letter like C:\...) needs
    # escaping - and that escaping is finicky and inconsistent across ffmpeg
    # versions. Sidestep it entirely: copy the font next to the segment and
    # run ffmpeg with that as its cwd, so the filter can reference it by a
    # bare filename that never contains a colon.
    local_font = work_dir / f"font{Path(font_path).suffix}"
    shutil.copyfile(font_path, local_font)

    filter_complex, v_label, a_label = build_filter_complex(
        offset, duration, thumbnail_text, captions=captions, font_path=local_font.name,
        crop_x=crop_x, crop_y=crop_y,
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
    subprocess.run(cmd, check=True, cwd=work_dir)
    return RenderResult(output_path=out_path)
