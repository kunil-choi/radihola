"""Cut a segment of the source video into a vertical (9:16) shorts clip.

Style (matches the reference https://www.youtube.com/shorts/-xAF_GxDIBU):
  - a black title band across the top, up to two lines of bold text (first
    line white, second line gold) taken from ``thumbnail_text`` split on a
    newline
  - the source video cropped to fill the rest of the canvas edge to edge (no
    letterboxing/blur), face-detected where possible so a speaker isn't cut
    out of frame by a blind center crop - biased to the right-hand camera
    (the guest, in this show's studio layout) over the left (the host) when
    both are in frame, see ``_face_crop_offset``
  - our own station/show wordmarks in the top-left/top-right corners of the
    video (real logo images if present at ``LOGO_LEFT_IMAGE``/
    ``LOGO_RIGHT_IMAGE``, else a text placeholder)
  - a second black band at the very bottom showing which original show this
    clip was cut from (the content is repurposed from another channel's
    broadcast, so this credits the source - see ``SOURCE_LOGO_TEXT``)
  - burned-in captions synced to the transcript segments that fall within
    the clip, bold white text in a full-width dark band near the bottom
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
# a little breathing room between the very top edge of the video and the
# title text - flush against the edge (the old TITLE_LINE1_Y=70) read as
# uncomfortably tight
TITLE_TOP_MARGIN = 36
TITLE_LINE1_Y = 82 + TITLE_TOP_MARGIN
TITLE_LINE2_Y = 185 + TITLE_TOP_MARGIN
# same-color outline (a common faux-bold trick) rendered blurry/mushy at
# this size instead of reading as heavier, so weight comes from the font
# file (already NanumGothicBold) and from size alone, not an outline
TITLE_FONTSIZE = 72
ACCENT_COLOR = "gold"

# our own station/corner wordmarks, top-left/top-right. Prefers a real logo
# image (drop the file in at the path below); falls back to text if the
# file doesn't exist, so this works before the assets are supplied too.
LOGO_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "logos"
LOGO_LEFT_IMAGE = LOGO_ASSETS_DIR / "kbs1radio_wordmark.png"
LOGO_RIGHT_IMAGE = LOGO_ASSETS_DIR / "kbs1radio_badge.png"
LOGO_IMAGE_HEIGHT = 210  # 30% smaller than the previous 300
# real logo aspect ratios vary; cap width too (fit-in-box, not just height)
# so two side-by-side logos can't overlap or run off a 1080px-wide canvas
LOGO_IMAGE_MAX_WIDTH = 221  # 30% smaller than the previous 315
LOGO_LEFT_TEXT = "KBS 1 Radio"
LOGO_RIGHT_TEXT = "라디올라"
LOGO_FONTSIZE = 35  # 30% smaller than the previous 50
# small margins so the logos read as sitting right in the video's top
# corners, not floating inward from the edges. LOGO_MARGIN_Y is the gap
# between the top edge of the video area (bottom of the title band) and
# the top of the logo - a small breathing room, not flush (0px read as
# too tight against the title band)
LOGO_MARGIN_X = 20
LOGO_MARGIN_Y = 6

# bottom black band crediting the source show the clip was cut from. Text
# placeholder until a real logo image is supplied; render_short() fills in
# the actual show name per-video when it's known (see cli.py's
# _guess_show_name()/program_name lookup).
SOURCE_LOGO_TEXT = "머니올라"
SOURCE_BAND_H = 130
SOURCE_LOGO_FONTSIZE = 58

# captions sit in a full-width dark band overlaid on the video, near the
# bottom, just above the source-credit band
CAPTION_FONTSIZE = 62
CAPTION_BAND_H = 200
CAPTION_BAND_GAP_ABOVE_SOURCE = 20
CAPTION_BAND_BOTTOM_MARGIN = SOURCE_BAND_H + CAPTION_BAND_GAP_ABOVE_SOURCE
CAPTION_BAND_TOP = CANVAS_H - CAPTION_BAND_BOTTOM_MARGIN - CAPTION_BAND_H
CAPTION_TEXT_PADDING_TOP = 25
CAPTION_LINE_HEIGHT = round(CAPTION_FONTSIZE * 1.25)
CAPTION_MAX_CHARS_PER_LINE = 14
CAPTION_BOX_OPACITY = 0.75


def escape_drawtext(text: str, keep_newlines: bool = False) -> str:
    """Escape a string for safe use inside an ffmpeg drawtext filter argument.

    Every drawtext call is built with expansion=none (see build_filter_complex),
    which turns off drawtext's own %{...} expansion mini-language entirely -
    that's what a literal '%' in real captions (e.g. "20%p 폭락") needs to
    survive intact; backslash-escaping it (the naive fix) does not work, as
    verified against a real ffmpeg build ("Stray %" warning persists either
    way since expansion runs as a separate parsing pass after this value is
    already extracted).
    """
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "’")  # avoid unbalanced quotes inside the filter
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
    src_w: float,
) -> tuple[int, int] | None:
    """Given detected face boxes (x, y, w, h) in original-frame pixel coords,
    return the (x, y) crop offset - in scaled-frame pixel coords - that keeps
    the most prominent face(s) inside a canvas_w x canvas_h crop window,
    biased to leave headroom above the face rather than dead-centering it.
    None if no faces were given.

    A static multi-camera composite (e.g. host and guest, each in their own
    camera box side by side) has a face on each side of every sampled frame.
    Averaging all of them just re-centers the crop on the seam between the
    two cameras - exactly where you don't want it. Instead, cluster faces by
    which half of the source frame they're in (split at src_w/2) and always
    go with the right-hand cluster when it has any faces at all: in this
    show's studio layout the guest (출연자, whose commentary the clips are
    actually built from) sits on the right and the host on the left, so
    picking "whichever side has more/bigger faces" can wrongly land on the
    host's camera in frames where their face happens to be bigger or more
    frontal. Only fall back to the left cluster when no face was found on
    the right at all (e.g. a momentary cutaway or single-camera shot).
    """
    if not faces:
        return None
    midpoint = src_w / 2
    left = [f for f in faces if f[0] + f[2] / 2 < midpoint]
    right = [f for f in faces if f[0] + f[2] / 2 >= midpoint]
    dominant = right if right else left

    total_area = 0.0
    weighted_x = 0.0
    weighted_y = 0.0
    for x, y, w, h in dominant:
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


# tried in order; radio-studio shots are often side-lit/angled enough that
# the default frontal cascade alone misses faces the alt2 cascade catches
_FACE_CASCADES = ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml")


def _detect_faces(image_path: Path) -> list[tuple[float, float, float, float]]:
    """Detect faces in a single image, returning (x, y, w, h) boxes in pixel
    coords. Empty on any failure (no opencv installed, a build/version that
    dropped CascadeClassifier, unreadable image, etc.) - callers treat that
    the same as "no faces found"."""
    try:
        import cv2
    except ImportError as e:
        print(f"[render] opencv를 불러올 수 없어 얼굴 인식을 건너뜁니다: {e}")
        return []
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return []
        gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        boxes: list[tuple[float, float, float, float]] = []
        for cascade_name in _FACE_CASCADES:
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + cascade_name)
            found = cascade.detectMultiScale(
                gray, scaleFactor=1.05, minNeighbors=3, minSize=(30, 30)
            )
            boxes.extend((float(x), float(y), float(w), float(h)) for x, y, w, h in found)
        return boxes
    except (AttributeError, cv2.error) as e:
        print(f"[render] 얼굴 인식 실패, 가운데 크롭을 사용합니다: {e}")
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
    except ImportError as e:
        print(f"[render] opencv 미설치/로드 실패로 가운데 크롭을 사용합니다: {e}")
        return default

    dims = _probe_dimensions(segment_path)
    if dims is None:
        print("[render] ffprobe 실패로 가운데 크롭을 사용합니다.")
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
    except subprocess.CalledProcessError as e:
        print(f"[render] 프레임 추출 실패로 가운데 크롭을 사용합니다: {e}")
        return default
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)

    offset = _face_crop_offset(all_faces, scale, canvas_w, canvas_h, scaled_w, scaled_h, src_w)
    if offset is None:
        print("[render] 샘플 프레임에서 얼굴을 찾지 못해 가운데 크롭을 사용합니다.")
        return default
    print(f"[render] 얼굴 {len(all_faces)}개 인식, 크롭 위치 조정: x={offset[0]}, y={offset[1]}")
    return str(offset[0]), str(offset[1])


def _logo_content_bbox(image_path: Path) -> tuple[int, int, int, int] | None:
    """Return the (left, top, right, bottom) pixel box of a logo PNG's
    non-transparent content, or None if it can't be determined.

    Real logo artwork is often exported on a much larger square canvas than
    the visible mark itself, padded with transparent pixels. Left uncropped,
    that padding scales along with the logo and reappears as visible empty
    space between the video's top edge and the logo once overlaid - fixing
    it requires cropping to the actual content before scaling, not just
    tightening the overlay margin.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(image_path) as img:
            alpha = img.convert("RGBA").split()[-1]
            return alpha.getbbox()
    except Exception:
        return None


def _logo_overlay_y(bbox: tuple[int, int, int, int] | None) -> int:
    """Vertical overlay offset for a top-corner logo, centered within the
    shared LOGO_IMAGE_HEIGHT box instead of just top-aligned.

    The left (wordmark) and right (badge) logos have very different aspect
    ratios, so scaling each to fit the same box (force_original_aspect_ratio
    =decrease) leaves them at different actual heights - top-aligning both
    at the same y then puts their centers out of line with each other (the
    shorter one reads as sitting higher). Centering both within the same
    box height instead lines up their midpoints regardless of shape.
    Falls back to the plain top-aligned offset when bbox is unavailable
    (PIL missing), since the scaled height can't be computed without it.
    """
    base_y = TITLE_BAND_H + LOGO_MARGIN_Y
    if bbox is None:
        return base_y
    content_w, content_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    scale = min(LOGO_IMAGE_MAX_WIDTH / content_w, LOGO_IMAGE_HEIGHT / content_h)
    scaled_h = content_h * scale
    return base_y + round((LOGO_IMAGE_HEIGHT - scaled_h) / 2)


def build_filter_complex(
    offset: float,
    duration: float,
    thumbnail_text: str,
    captions: list[tuple[float, float, str]] | None = None,
    font_path: str = DEFAULT_FONT,
    logo_left_image: Path | None = LOGO_LEFT_IMAGE,
    logo_right_image: Path | None = LOGO_RIGHT_IMAGE,
    logo_left_text: str | None = LOGO_LEFT_TEXT,
    logo_right_text: str | None = LOGO_RIGHT_TEXT,
    source_logo_text: str | None = SOURCE_LOGO_TEXT,
    crop_x: str = "(in_w-out_w)/2",
    crop_y: str = "(in_h-out_h)/2",
) -> tuple[str, str, str, list[Path]]:
    """Return (filter_complex, video_map_label, audio_map_label, extra_inputs).

    crop_x/crop_y are ffmpeg crop-filter position expressions (or plain pixel
    offsets), in the coordinate space of the scaled frame. Defaults to a plain
    center crop; render_short() overrides them with a face-detected offset
    when possible so a speaker isn't cropped out by a blind center crop.

    extra_inputs is the ordered list of image files (logo_left_image/
    logo_right_image, whichever exist on disk) that the caller must also
    pass as ffmpeg "-i" arguments, in this order, right after the main video
    input - the filter graph references them as [1:v], [2:v], etc.
    """
    end = offset + duration
    captions = captions or []
    video_h = CANVAS_H - TITLE_BAND_H - SOURCE_BAND_H
    extra_inputs: list[Path] = []

    stages = [
        f"[0:v]trim=start={offset}:end={end},setpts=PTS-STARTPTS,"
        f"scale={CANVAS_W}:{video_h}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{video_h}:{crop_x}:{crop_y}[cropped]",
        # video sits between the top title band and the bottom source-credit
        # band; padding to the full canvas leaves both as black automatically
        f"[cropped]pad={CANVAS_W}:{CANVAS_H}:0:{TITLE_BAND_H}:color=black[padded]",
    ]

    line1, line2 = _title_lines(thumbnail_text)
    last = "padded"
    stages.append(
        f"[{last}]drawtext=fontfile={font_path}:expansion=none:text='{escape_drawtext(line1)}':"
        f"fontcolor=white:fontsize={TITLE_FONTSIZE}:"
        f"x=(w-text_w)/2:y={TITLE_LINE1_Y}[t1]"
    )
    last = "t1"
    if line2:
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:expansion=none:text='{escape_drawtext(line2)}':"
            f"fontcolor={ACCENT_COLOR}:fontsize={TITLE_FONTSIZE}:"
            f"x=(w-text_w)/2:y={TITLE_LINE2_Y}[t2]"
        )
        last = "t2"

    if logo_left_image is not None and logo_left_image.is_file():
        extra_inputs.append(logo_left_image)
        idx = len(extra_inputs)
        bbox = _logo_content_bbox(logo_left_image)
        crop_stage = (
            f"crop={bbox[2] - bbox[0]}:{bbox[3] - bbox[1]}:{bbox[0]}:{bbox[1]}," if bbox else ""
        )
        # the KBS wordmark artwork is navy on transparent, which reads as
        # nearly invisible over a busy video background; force it to solid
        # white (alpha untouched) so it has the same bright contrast as the
        # right-side badge logo, which is already white-on-navy
        stages.append(
            f"[{idx}:v]{crop_stage}scale=w={LOGO_IMAGE_MAX_WIDTH}:h={LOGO_IMAGE_HEIGHT}:"
            f"force_original_aspect_ratio=decrease,format=rgba,lutrgb=r=255:g=255:b=255[lgimg{idx}]"
        )
        stages.append(
            f"[{last}][lgimg{idx}]overlay=x={LOGO_MARGIN_X}:y={_logo_overlay_y(bbox)}[lg1]"
        )
        last = "lg1"
    elif logo_left_text:
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:expansion=none:text='{escape_drawtext(logo_left_text)}':"
            f"fontcolor=white:fontsize={LOGO_FONTSIZE}:"
            f"x={LOGO_MARGIN_X}:y={TITLE_BAND_H + LOGO_MARGIN_Y}[lg1]"
        )
        last = "lg1"

    if logo_right_image is not None and logo_right_image.is_file():
        extra_inputs.append(logo_right_image)
        idx = len(extra_inputs)
        bbox = _logo_content_bbox(logo_right_image)
        crop_stage = (
            f"crop={bbox[2] - bbox[0]}:{bbox[3] - bbox[1]}:{bbox[0]}:{bbox[1]}," if bbox else ""
        )
        stages.append(
            f"[{idx}:v]{crop_stage}scale=w={LOGO_IMAGE_MAX_WIDTH}:h={LOGO_IMAGE_HEIGHT}:"
            f"force_original_aspect_ratio=decrease[lgimg{idx}]"
        )
        stages.append(
            f"[{last}][lgimg{idx}]overlay=x=main_w-overlay_w-{LOGO_MARGIN_X}:"
            f"y={_logo_overlay_y(bbox)}[lg2]"
        )
        last = "lg2"
    elif logo_right_text:
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:expansion=none:text='{escape_drawtext(logo_right_text)}':"
            f"fontcolor=white:fontsize={LOGO_FONTSIZE}:"
            f"x=w-text_w-{LOGO_MARGIN_X}:y={TITLE_BAND_H + LOGO_MARGIN_Y}[lg2]"
        )
        last = "lg2"

    if source_logo_text:
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:expansion=none:text='{escape_drawtext(source_logo_text)}':"
            f"fontcolor=white:fontsize={SOURCE_LOGO_FONTSIZE}:"
            f"x=(w-text_w)/2:y=h-{SOURCE_BAND_H // 2}-{SOURCE_LOGO_FONTSIZE // 2}[srclogo]"
        )
        last = "srclogo"

    for i, (cue_start, cue_end, text) in enumerate(captions):
        enable = f"enable='between(t,{cue_start},{cue_end})'"
        wrapped = _wrap_caption(text)
        cap_lines = wrapped.split("\n", 1)
        cap_line1 = cap_lines[0]
        cap_line2 = cap_lines[1] if len(cap_lines) > 1 else None

        band_label = f"capband{i}"
        stages.append(
            f"[{last}]drawbox=x=0:y={CAPTION_BAND_TOP}:w={CANVAS_W}:h={CAPTION_BAND_H}:"
            f"color=black@{CAPTION_BOX_OPACITY}:t=fill:{enable}[{band_label}]"
        )
        last = band_label

        line1_y = CAPTION_BAND_TOP + CAPTION_TEXT_PADDING_TOP
        label = f"cap{i}a"
        stages.append(
            f"[{last}]drawtext=fontfile={font_path}:expansion=none:text='{escape_drawtext(cap_line1)}':"
            f"fontcolor=white:fontsize={CAPTION_FONTSIZE}:borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y={line1_y}:{enable}[{label}]"
        )
        last = label

        if cap_line2:
            line2_y = line1_y + CAPTION_LINE_HEIGHT
            label2 = f"cap{i}b"
            stages.append(
                f"[{last}]drawtext=fontfile={font_path}:expansion=none:text='{escape_drawtext(cap_line2)}':"
                f"fontcolor=white:fontsize={CAPTION_FONTSIZE}:borderw=3:bordercolor=black:"
                f"x=(w-text_w)/2:y={line2_y}:{enable}[{label2}]"
            )
            last = label2

    stages.append(f"[{last}]null[vout]")
    stages.append(f"[0:a]atrim=start={offset}:end={end},asetpts=PTS-STARTPTS[aout]")

    return ";".join(stages), "[vout]", "[aout]", extra_inputs


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
    source_logo_text: str | None = SOURCE_LOGO_TEXT,
) -> RenderResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    # keyed by start/end, not just video_id - otherwise re-rendering a
    # different candidate from the same source video reuses whatever segment
    # was downloaded for a previous candidate instead of downloading its own
    segment_path = work_dir / f"{video_id}_{start_sec:g}-{end_sec:g}_segment.mp4"
    youtube.download_segment(video_id, start_sec, end_sec, segment_path, pad_sec=pad_sec)

    pad_start = max(0.0, start_sec - pad_sec)
    offset = start_sec - pad_start
    duration = end_sec - start_sec

    captions = _relative_captions(segments or [], start_sec, end_sec)

    video_h = CANVAS_H - TITLE_BAND_H - SOURCE_BAND_H
    crop_x, crop_y = find_speaker_crop(segment_path, CANVAS_W, video_h)

    # ffmpeg's filter option syntax uses ':' as a key=value separator, so a raw
    # font path containing one (e.g. a Windows drive letter like C:\...) needs
    # escaping - and that escaping is finicky and inconsistent across ffmpeg
    # versions. Sidestep it entirely: copy the font next to the segment and
    # run ffmpeg with that as its cwd, so the filter can reference it by a
    # bare filename that never contains a colon.
    local_font = work_dir / f"font{Path(font_path).suffix}"
    shutil.copyfile(font_path, local_font)

    filter_complex, v_label, a_label, extra_inputs = build_filter_complex(
        offset, duration, thumbnail_text, captions=captions, font_path=local_font.name,
        crop_x=crop_x, crop_y=crop_y, source_logo_text=source_logo_text,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(segment_path)]
    for image_path in extra_inputs:
        cmd += ["-i", str(image_path)]
    cmd += [
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
