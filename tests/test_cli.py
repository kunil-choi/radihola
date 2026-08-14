import json
from unittest.mock import patch

from radihola import cli
from radihola.cli import _guess_show_name, build_parser


def test_list_command_parses():
    parser = build_parser()
    args = parser.parse_args(["list", "--program", "leedaeho"])
    assert args.program == "leedaeho"


def test_render_command_parses():
    parser = build_parser()
    args = parser.parse_args(
        [
            "render",
            "--video-id",
            "abc123",
            "--start",
            "1.5",
            "--end",
            "40",
            "--thumbnail-text",
            "hi",
            "--out",
            "/tmp/out.mp4",
        ]
    )
    assert args.video_id == "abc123"
    assert args.start == 1.5


def test_render_command_parses_captions_json():
    parser = build_parser()
    args = parser.parse_args(
        [
            "render",
            "--video-id",
            "abc123",
            "--start",
            "1.5",
            "--end",
            "40",
            "--thumbnail-text",
            "hi",
            "--out",
            "/tmp/out.mp4",
            "--captions-json",
            '[{"start_sec": 1.5, "end_sec": 3.0, "text": "hello"}]',
        ]
    )
    assert args.captions_json == '[{"start_sec": 1.5, "end_sec": 3.0, "text": "hello"}]'


def test_guess_show_name_leedaeho():
    assert _guess_show_name("성공예감 이대호입니다 2부 - 8월 5일") == "성공예감 이대호입니다"


def test_guess_show_name_kyungjeshow():
    assert _guess_show_name("경제쇼 8월 5일 방송분") == "경제쇼"


def test_guess_show_name_falls_back_to_custom_program_name():
    assert _guess_show_name("전혀 관계없는 제목") == "머니올라"


def _write_group(tmp_path, program="custom", date_key="VID123", part="main"):
    out_dir = tmp_path / program / date_key / part
    out_dir.mkdir(parents=True)
    candidates_data = {
        "program": program,
        "program_name": "머니올라",
        "date": "2026-08-14",
        "part": part,
        "video_id": "VID123",
        "guest_label": "홍길동",
        "candidates": [
            {
                "id": 1,
                "start_sec": 10.0,
                "end_sec": 20.0,
                "thumbnail_text": "제목",
                "captions": [{"start_sec": 10.0, "end_sec": 15.0, "text": "candidate caption"}],
            }
        ],
    }
    (out_dir / "candidates.json").write_text(
        json.dumps(candidates_data, ensure_ascii=False), encoding="utf-8"
    )
    transcript_data = {
        "source": "youtube_captions",
        "segments": [
            {"start_sec": 0.0, "end_sec": 5.0, "text": "intro"},
            {"start_sec": 30.0, "end_sec": 35.0, "text": "custom range caption"},
        ],
    }
    (out_dir / "transcript.json").write_text(
        json.dumps(transcript_data, ensure_ascii=False), encoding="utf-8"
    )
    return out_dir


def test_get_captions_for_range_prefers_stored_candidate_captions(tmp_path, monkeypatch):
    _write_group(tmp_path)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)

    segments = cli.get_captions_for_range("custom", "VID123", 10.0, 20.0)

    assert [s.text for s in segments] == ["candidate caption"]


def test_get_captions_for_range_falls_back_to_transcript_for_custom_ranges(tmp_path, monkeypatch):
    _write_group(tmp_path)
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path)

    segments = cli.get_captions_for_range("custom", "VID123", 28.0, 40.0)

    assert [s.text for s in segments] == ["custom range caption"]


def test_cmd_render_explicit_captions_json_overrides_candidate_file(tmp_path, monkeypatch):
    out_dir = _write_group(tmp_path)
    candidate_file = out_dir / "candidates.json"

    captured = {}

    def fake_render_short(**kwargs):
        captured.update(kwargs)
        return cli.render.RenderResult(output_path=kwargs["out_path"])

    with patch.object(cli.render, "render_short", side_effect=fake_render_short):
        args = cli.build_parser().parse_args(
            [
                "render",
                "--candidate-file",
                str(candidate_file),
                "--candidate-id",
                "1",
                "--out",
                str(tmp_path / "out.mp4"),
                "--captions-json",
                '[{"start_sec": 10.0, "end_sec": 12.0, "text": "reviewer edited"}]',
            ]
        )
        cli.cmd_render(args)

    assert [s.text for s in captured["segments"]] == ["reviewer edited"]
