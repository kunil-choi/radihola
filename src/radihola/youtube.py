"""Thin wrappers around yt-dlp for listing playlists and downloading media."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import yt_dlp

from .config import PartRule, ProgramConfig


@dataclass
class VideoEntry:
    video_id: str
    title: str
    url: str
    upload_date: str | None = None  # YYYYMMDD
    duration: int | None = None  # seconds


_VIDEO_ID_RE = re.compile(r"^[\w-]{11}$")
_URL_VIDEO_ID_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?(?:.*&)?v=|youtube\.com/shorts/|youtube\.com/embed/|youtu\.be/)([\w-]{11})"),
)


def extract_video_id(url_or_id: str) -> str:
    """Pull an 11-char video id out of a YouTube URL, or pass through a bare id."""
    candidate = url_or_id.strip()
    if _VIDEO_ID_RE.match(candidate):
        return candidate
    for pattern in _URL_VIDEO_ID_PATTERNS:
        m = pattern.search(candidate)
        if m:
            return m.group(1)
    raise ValueError(f"couldn't find a YouTube video id in {url_or_id!r}")


def _base_ydl_opts(extra: dict | None = None) -> dict:
    """Common yt-dlp options.

    YouTube aggressively rate-limits/blocks requests from cloud IPs (the
    "Sign in to confirm you're not a bot" error is common on GitHub Actions
    runners). Mitigation depends on whether a cookies file (YTDLP_COOKIES_FILE,
    exported from a real, logged-in browser session) is available:

    - with cookies: use the web client (first in the list = preferred). The
      android/tv clients don't accept web-session cookies properly and were
      observed returning "Requested format is not available" for every
      video once cookies were added, even though the sign-in check itself
      passed.
    - without cookies: prefer the android/tv player clients, since they
      don't need the same web sign-in check as the default web client.
    """
    cookies_file = os.environ.get("YTDLP_COOKIES_FILE")
    player_client = ["web", "android", "tv"] if cookies_file else ["android", "tv", "web"]
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": player_client}},
    }
    if cookies_file:
        opts["cookiefile"] = cookies_file
    if extra:
        opts.update(extra)
    return opts


def _flat_playlist_entries(playlist_url: str, limit: int = 20) -> list[dict]:
    ydl_opts = _base_ydl_opts(
        {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "playlistend": limit,
        }
    )
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
    return info.get("entries") or []


def get_video_info(video_id: str) -> VideoEntry:
    """Fetch title/upload_date/duration only, without resolving/selecting formats.

    process=False skips yt-dlp's format-selection step entirely. That step is
    what breaks (with "Requested format is not available") once YouTube
    requires a PO token for the formats list of a cookie-authenticated
    session; skipping it is safe here since we only need metadata fields,
    which the extractor already fills in before format selection runs.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = _base_ydl_opts({"skip_download": True})
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False, process=False)
    return VideoEntry(
        video_id=info["id"],
        title=info.get("title", ""),
        url=url,
        upload_date=info.get("upload_date"),
        duration=info.get("duration"),
    )


def list_recent_videos(playlist_url: str, limit: int = 20) -> list[VideoEntry]:
    """List the most recent entries of a playlist, with upload_date/duration filled in.

    This does one lightweight "flat" listing call for the playlist, then one
    metadata call per candidate entry (needed because flat listing does not
    reliably include upload_date/duration).
    """
    entries = _flat_playlist_entries(playlist_url, limit=limit)
    out: list[VideoEntry] = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        try:
            out.append(get_video_info(vid))
        except Exception:
            # skip videos that fail to resolve (deleted/private/etc.)
            continue
    return out


def matches_part(title: str, rule: PartRule) -> bool:
    if any(re.search(pat, title) for pat in rule.exclude):
        return False
    if not rule.include:
        return True
    return any(re.search(pat, title) for pat in rule.include)


def find_todays_parts(
    program: ProgramConfig, limit: int = 20, today: date | None = None
) -> dict[str, VideoEntry | None]:
    """Find the most recent video matching each part rule of a program.

    Looks at videos uploaded within ``program.lookback_days`` of ``today``
    (defaults to real today), and for each part rule returns the most recent
    matching video (or None if nothing matched).
    """
    today = today or date.today()
    cutoff = today - timedelta(days=program.lookback_days)

    entries = list_recent_videos(program.playlist_url, limit=limit)

    def in_window(e: VideoEntry) -> bool:
        if not e.upload_date:
            return True
        try:
            d = datetime.strptime(e.upload_date, "%Y%m%d").date()
        except ValueError:
            return True
        return d >= cutoff

    windowed = [e for e in entries if in_window(e)]

    result: dict[str, VideoEntry | None] = {}
    for rule in program.parts:
        match = next((e for e in windowed if matches_part(e.title, rule)), None)
        result[rule.key] = match
    return result


def download_audio(video_id: str, out_dir: Path) -> Path:
    """Download best-audio only, for transcript generation. Returns the mp3 path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / f"{video_id}.%(ext)s")
    ydl_opts = _base_ydl_opts(
        {
            "format": "bestaudio/best",
            "outtmpl": out_tmpl,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
        }
    )
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return out_dir / f"{video_id}.mp3"


def download_auto_captions(video_id: str, out_dir: Path, lang: str = "ko") -> Path | None:
    """Try to fetch existing (manual or auto-generated) captions as vtt.

    Returns the path to the .vtt file, or None if no captions were available.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / f"{video_id}")
    ydl_opts = _base_ydl_opts(
        {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt",
            "outtmpl": out_tmpl,
            # skip_download=True still runs format selection (for filename
            # templating etc.), which fails with "Requested format is not
            # available" under the same PO-token gating as get_video_info.
            # We don't need any video/audio format here, only subtitles, so
            # ignore that failure instead of aborting the whole call.
            "ignore_no_formats_error": True,
        }
    )
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    candidates = list(out_dir.glob(f"{video_id}*.{lang}.vtt"))
    return candidates[0] if candidates else None


def download_segment(
    video_id: str, start_sec: float, end_sec: float, out_path: Path, pad_sec: float = 1.5
) -> Path:
    """Download only the [start-pad, end+pad] section of a video (video+audio muxed)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pad_start = max(0.0, start_sec - pad_sec)
    pad_end = end_sec + pad_sec
    ydl_opts = _base_ydl_opts(
        {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(out_path.with_suffix("")) + ".%(ext)s",
            "download_ranges": yt_dlp.utils.download_range_func(None, [(pad_start, pad_end)]),
            "force_keyframes_at_cuts": True,
            "merge_output_format": "mp4",
            # each render's segment path is keyed by its own start/end, but
            # be defensive: never silently reuse a stale file left over from
            # a previous (e.g. interrupted) run at the same path
            "overwrites": True,
        }
    )
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    produced = out_path.with_suffix(".mp4")
    if produced != out_path and produced.exists():
        produced.rename(out_path)
    return out_path
