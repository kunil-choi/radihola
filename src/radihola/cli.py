from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

from . import analyze, render, transcript, youtube
from .config import PROGRAMS, get_program

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
WORK_DIR = REPO_ROOT / "work"


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


def _analyze_one(program_key: str, part_key: str, video: youtube.VideoEntry) -> Path:
    program = get_program(program_key)
    today = date.today().isoformat()
    work_dir = WORK_DIR / program_key / video.video_id
    segments, source = transcript.get_transcript(video.video_id, work_dir)
    if not segments:
        raise SystemExit(f"no transcript could be produced for {video.video_id}")

    candidates = analyze.propose_candidates(segments, program, video.title)

    out_dir = DATA_DIR / program_key / today / part_key
    out_dir.mkdir(parents=True, exist_ok=True)

    candidate_dicts = []
    for i, c in enumerate(candidates, start=1):
        d = analyze.candidate_to_dict(c)
        d["id"] = i
        candidate_dicts.append(d)

    result = {
        "program": program_key,
        "program_name": program.name,
        "date": today,
        "part": part_key,
        "video_id": video.video_id,
        "video_url": video.url,
        "video_title": video.title,
        "duration_sec": video.duration,
        "transcript_source": source,
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
        _analyze_one(args.program, rule.key, video)

    if not any_found:
        print("no parts matched; nothing to analyze", file=sys.stderr)
        sys.exit(1)


def cmd_render(args: argparse.Namespace) -> None:
    start_sec = args.start
    end_sec = args.end
    thumbnail_text = args.thumbnail_text

    if args.candidate_file:
        data = json.loads(Path(args.candidate_file).read_text(encoding="utf-8"))
        cand = next(c for c in data["candidates"] if c["id"] == args.candidate_id)
        start_sec = cand["start_sec"]
        end_sec = cand["end_sec"]
        thumbnail_text = thumbnail_text or cand["thumbnail_text"]
        video_id = data["video_id"]
    else:
        video_id = args.video_id

    if not video_id or start_sec is None or end_sec is None or not thumbnail_text:
        raise SystemExit("--video-id/--start/--end/--thumbnail-text are required "
                          "(or pass --candidate-file/--candidate-id)")

    out_path = Path(args.out)
    work_dir = WORK_DIR / "render" / video_id
    result = render.render_short(
        video_id=video_id,
        start_sec=float(start_sec),
        end_sec=float(end_sec),
        thumbnail_text=thumbnail_text,
        out_path=out_path,
        work_dir=work_dir,
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

    p_render = sub.add_parser("render", help="render a chosen candidate into a vertical shorts mp4")
    p_render.add_argument("--program", required=False, help="unused, kept for symmetry with the Actions inputs")
    p_render.add_argument("--video-id")
    p_render.add_argument("--start", type=float)
    p_render.add_argument("--end", type=float)
    p_render.add_argument("--thumbnail-text")
    p_render.add_argument("--candidate-file", help="candidates.json to pull start/end/text from")
    p_render.add_argument("--candidate-id", type=int, default=1, help="candidate 'id' field within --candidate-file (1-based)")
    p_render.add_argument("--out", required=True)
    p_render.set_defaults(func=cmd_render)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
