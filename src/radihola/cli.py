from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import analyze, render, transcript, youtube
from .config import CUSTOM_PROGRAM, PROGRAMS, ProgramConfig, get_program

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
WORK_DIR = REPO_ROOT / "work"

# analyze-url doesn't ask which show a video belongs to, so the bottom logo
# text is guessed from the video title using the same kind of pattern the
# scheduled programs already match on (see config.py's PartRule regexes)
_SHOW_NAME_PATTERNS = (
    (r"이대호", "성공예감 이대호입니다"),
    (r"경제", "경제쇼"),
)


def _guess_show_name(video_title: str) -> str:
    for pattern, name in _SHOW_NAME_PATTERNS:
        if re.search(pattern, video_title):
            return name
    return CUSTOM_PROGRAM.name


def cmd_list(args: argparse.Namespace) -> None:
    program = get_program(args.program)
    print(f"# {program.name} ({program.playlist_url})")
    entries = youtube.list_recent_videos(program.playlist_url, limit=args.limit)
    parts = youtube.find_todays_parts(program, limit=args.limit)

    print("\n## recent playlist entries")
    for e in entries:
        matched = [
            rule.label
            for rule in program.parts
            if youtube.matches_part(e.title, rule)
        ]
        tag = f" -> {', '.join(matched)}" if matched else ""
        print(f"- [{e.upload_date}] {e.video_id} {e.title}{tag}")

    print("\n## selected parts for today's pipeline run")
    for rule in program.parts:
        entry = parts.get(rule.key)
        if entry is None:
            print(f"- {rule.label}: (no match found)")
        else:
            print(f"- {rule.label}: {entry.video_id} — {entry.title}")


def _analyze_and_write(
    program: ProgramConfig,
    program_key: str,
    date_key: str,
    part_key: str,
    video: youtube.VideoEntry,
) -> Path:
    work_dir = WORK_DIR / program_key / video.video_id
    segments, source = transcript.get_transcript(video.video_id, work_dir)
    if not segments:
        raise SystemExit(f"no transcript could be produced for {video.video_id}")

    candidates = analyze.propose_candidates(segments, program, video.title)
    guest_label = analyze.extract_guest_info(video.title, video.description)

    # YouTube's auto-captions are plain speech recognition with no context,
    # so they mishear words fairly often. Batch-correct just the segments
    # that actually get used (burned into a rendered short, shown as the
    # excerpt on the review page) in one API call rather than the whole
    # transcript - much cheaper, and it's all viewers ever see anyway.
    per_candidate_segments = [
        transcript.segments_in_range(segments, c.start_sec, c.end_sec) for c in candidates
    ]
    flat_texts = [s.text for segs in per_candidate_segments for s in segs]
    corrected_texts = iter(analyze.correct_caption_errors(flat_texts))
    per_candidate_segments = [
        [dataclasses.replace(s, text=next(corrected_texts)) for s in segs]
        for segs in per_candidate_segments
    ]

    out_dir = DATA_DIR / program_key / date_key / part_key
    out_dir.mkdir(parents=True, exist_ok=True)

    candidate_dicts = []
    for i, (c, cap_segs) in enumerate(zip(candidates, per_candidate_segments), start=1):
        d = analyze.candidate_to_dict(c)
        d["id"] = i
        d["transcript_excerpt"] = " ".join(s.text for s in cap_segs)
        d["captions"] = [dataclasses.asdict(s) for s in cap_segs]
        candidate_dicts.append(d)

    result = {
        "program": program_key,
        "program_name": program.name,
        "date": date.today().isoformat(),
        "part": part_key,
        "video_id": video.video_id,
        "video_url": video.url,
        "video_title": video.title,
        "duration_sec": video.duration,
        "transcript_source": source,
        # best-effort guess from the video description (see
        # analyze.extract_guest_info); shown as an editable field in the
        # webui so it can be corrected/filled in before rendering
        "guest_label": guest_label,
        "candidates": candidate_dicts,
    }
    out_path = out_dir / "candidates.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    transcript_path = out_dir / "transcript.json"
    transcript_path.write_text(
        json.dumps(
            {"source": source, "segments": [dataclasses.asdict(s) for s in segments]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out_path}")
    return out_path


def cmd_analyze(args: argparse.Namespace) -> None:
    program = get_program(args.program)
    parts = youtube.find_todays_parts(program, limit=args.limit)

    any_found = False
    for rule in program.parts:
        video = parts.get(rule.key)
        if video is None:
            print(f"[skip] {program.name} / {rule.label}: no matching video found")
            continue
        any_found = True
        print(f"[analyze] {program.name} / {rule.label}: {video.title} ({video.video_id})")
        _analyze_and_write(program, args.program, date.today().isoformat(), rule.key, video)

    if not any_found:
        print("no parts matched; nothing to analyze", file=sys.stderr)
        sys.exit(1)


def cmd_analyze_url(args: argparse.Namespace) -> None:
    video_id = youtube.extract_video_id(args.url)
    video = youtube.get_video_info(video_id)
    print(f"[analyze-url] {video.title} ({video.video_id})")
    program = dataclasses.replace(CUSTOM_PROGRAM, name=_guess_show_name(video.title))
    out_path = _analyze_and_write(program, "custom", video_id, "main", video)
    print(f"wrote {out_path}")


def _load_segments(transcript_path: Path) -> list[transcript.Segment]:
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    return [transcript.Segment(**s) for s in data["segments"]]


def _find_group_for_video(program_key: str | None, video_id: str) -> tuple[Path, dict] | None:
    """Find the candidates.json (path + parsed contents) for video_id."""
    pattern = f"{program_key}/*/*/candidates.json" if program_key else "*/*/*/candidates.json"
    for path in DATA_DIR.glob(pattern):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("video_id") == video_id:
            return path, data
    return None


def _captions_for_range_in_group(
    group_path: Path, group_data: dict, start_sec: float, end_sec: float
) -> list[transcript.Segment]:
    """Caption segments for [start_sec, end_sec] within an already-loaded
    candidates group: a stored candidate's pre-corrected captions if the
    range matches one exactly, else (uncorrected) captions derived from the
    group's full transcript.json. Shared by cmd_render's fallback caption
    lookup and get_captions_for_range (the webui's caption preview/edit
    endpoint for custom, non-candidate clip ranges).
    """
    for cand in group_data.get("candidates", []):
        if (
            abs(cand.get("start_sec", -1) - start_sec) < 0.01
            and abs(cand.get("end_sec", -1) - end_sec) < 0.01
            and cand.get("captions")
        ):
            return [transcript.Segment(**s) for s in cand["captions"]]
    transcript_path = group_path.parent / "transcript.json"
    if transcript_path.exists():
        segments = _load_segments(transcript_path)
        return transcript.segments_in_range(segments, start_sec, end_sec)
    return []


def get_captions_for_range(
    program_key: str | None, video_id: str, start_sec: float, end_sec: float
) -> list[transcript.Segment]:
    """Best-available caption segments for [start_sec, end_sec] on video_id,
    for the webui to show in its caption editor before a custom clip is
    rendered (candidate clips already carry their own c.captions)."""
    found = _find_group_for_video(program_key, video_id)
    if not found:
        return []
    group_path, group_data = found
    return _captions_for_range_in_group(group_path, group_data, start_sec, end_sec)


def cmd_render(args: argparse.Namespace) -> None:
    start_sec = args.start
    end_sec = args.end
    thumbnail_text = args.thumbnail_text
    transcript_path: Path | None = None
    logo_text: str | None = None
    # an explicit --guest-label always wins (the webui sends whatever the
    # reviewer confirmed/edited); only fall back to the stored group value
    # when it wasn't passed at all
    guest_label: str | None = getattr(args, "guest_label", None) or None
    caption_segments: list[transcript.Segment] | None = None

    # reviewer-edited captions (webui's caption editor) always win over
    # whatever is stored/derived below - the whole point is to let a human
    # correct them before rendering
    captions_json = getattr(args, "captions_json", None)
    if captions_json:
        caption_segments = [transcript.Segment(**s) for s in json.loads(captions_json)]

    if args.candidate_file:
        candidate_file = Path(args.candidate_file)
        data = json.loads(candidate_file.read_text(encoding="utf-8"))
        cand = next(c for c in data["candidates"] if c["id"] == args.candidate_id)
        start_sec = cand["start_sec"]
        end_sec = cand["end_sec"]
        thumbnail_text = thumbnail_text or cand["thumbnail_text"]
        video_id = data["video_id"]
        logo_text = data.get("program_name")
        if guest_label is None:
            guest_label = data.get("guest_label")
        if caption_segments is None and cand.get("captions"):
            caption_segments = [transcript.Segment(**s) for s in cand["captions"]]
        sibling = candidate_file.parent / "transcript.json"
        if sibling.exists():
            transcript_path = sibling
    else:
        video_id = args.video_id

    if not video_id or start_sec is None or end_sec is None or not thumbnail_text:
        raise SystemExit("--video-id/--start/--end/--thumbnail-text are required "
                          "(or pass --candidate-file/--candidate-id)")

    if transcript_path is None or logo_text is None or caption_segments is None or guest_label is None:
        found = _find_group_for_video(args.program, video_id)
        if found:
            group_path, group_data = found
            if transcript_path is None:
                sibling = group_path.parent / "transcript.json"
                if sibling.exists():
                    transcript_path = sibling
            if logo_text is None:
                logo_text = group_data.get("program_name")
            if guest_label is None:
                guest_label = group_data.get("guest_label")
            if caption_segments is None:
                caption_segments = _captions_for_range_in_group(
                    group_path, group_data, start_sec, end_sec
                ) or None

    # pre-corrected, time-filtered captions stored on the candidate (see
    # cli.py's _analyze_and_write) are preferred; only fall back to
    # re-deriving (uncorrected) captions from the full transcript.json for
    # candidates.json files written before that field existed
    if caption_segments is not None:
        segments = caption_segments
    else:
        segments = _load_segments(transcript_path) if transcript_path else []
    if not segments:
        print(
            f"[render] no transcript found for {video_id}; captions will be omitted",
            file=sys.stderr,
        )

    out_path = Path(args.out)
    work_dir = WORK_DIR / "render" / video_id
    result = render.render_short(
        video_id=video_id,
        start_sec=float(start_sec),
        end_sec=float(end_sec),
        thumbnail_text=thumbnail_text,
        out_path=out_path,
        work_dir=work_dir,
        segments=segments,
        source_logo_text=logo_text or render.SOURCE_LOGO_TEXT,
        guest_label_text=guest_label,
    )
    print(f"wrote {result.output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radihola")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="dry-run: list playlist entries and part matching")
    p_list.add_argument("--program", required=True, choices=sorted(PROGRAMS))
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_analyze = sub.add_parser("analyze", help="download+analyze today's parts, write candidates.json")
    p_analyze.add_argument("--program", required=True, choices=sorted(PROGRAMS))
    p_analyze.add_argument("--limit", type=int, default=20)
    p_analyze.set_defaults(func=cmd_analyze)

    p_analyze_url = sub.add_parser(
        "analyze-url", help="download+analyze an arbitrary video URL, write candidates.json"
    )
    p_analyze_url.add_argument("--url", required=True, help="YouTube video URL or bare video id")
    p_analyze_url.set_defaults(func=cmd_analyze_url)

    p_render = sub.add_parser("render", help="render a chosen candidate into a vertical shorts mp4")
    p_render.add_argument("--program", required=False, help="unused, kept for symmetry with the Actions inputs")
    p_render.add_argument("--video-id")
    p_render.add_argument("--start", type=float)
    p_render.add_argument("--end", type=float)
    p_render.add_argument("--thumbnail-text")
    p_render.add_argument("--candidate-file", help="candidates.json to pull start/end/text from")
    p_render.add_argument("--candidate-id", type=int, default=1, help="candidate 'id' field within --candidate-file (1-based)")
    p_render.add_argument(
        "--guest-label",
        help='on-screen guest name plate, e.g. "김은비 변호사 / 손해보험협회". '
        "defaults to the stored candidates.json value if omitted.",
    )
    p_render.add_argument(
        "--captions-json",
        help="JSON array of {start_sec,end_sec,text} objects overriding the stored/derived "
        "captions (e.g. reviewer-edited captions from the webui).",
    )
    p_render.add_argument("--out", required=True)
    p_render.set_defaults(func=cmd_render)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
