from unittest.mock import patch

from radihola import render as render_module
from radihola.render import (
    _face_crop_offset,
    _relative_captions,
    _title_lines,
    _wrap_caption,
    build_filter_complex,
    escape_drawtext,
)
from radihola.transcript import Segment


def test_escape_drawtext_colon_and_quote():
    escaped = escape_drawtext("이러다 다 망합니다: '진짜'?")
    assert "\\:" in escaped
    assert "'" not in escaped.replace("’", "")  # straight quote replaced


def test_escape_drawtext_strips_newline_unless_kept():
    assert "\n" not in escape_drawtext("한 줄\n두 줄")
    assert "\n" in escape_drawtext("한 줄\n두 줄", keep_newlines=True)


def test_title_lines_splits_on_newline():
    assert _title_lines("로봇택시\n취객은 누가 깨울까?") == ("로봇택시", "취객은 누가 깨울까?")
    assert _title_lines("한 줄짜리 제목") == ("한 줄짜리 제목", None)


def test_wrap_caption_short_text_unchanged():
    assert _wrap_caption("짧은 문구") == "짧은 문구"


def test_wrap_caption_long_text_breaks_on_space():
    wrapped = _wrap_caption("구글 웨이모에 어떤 일이 벌어졌냐면 말이죠")
    assert "\n" in wrapped
    assert all(len(line) > 0 for line in wrapped.split("\n"))


def test_relative_captions_filters_and_offsets():
    segments = [
        Segment(start_sec=0.0, end_sec=5.0, text="클립 밖"),
        Segment(start_sec=12.0, end_sec=15.0, text="클립 안"),
        Segment(start_sec=40.0, end_sec=45.0, text="클립 밖2"),
    ]
    out = _relative_captions(segments, start_sec=10.0, end_sec=30.0)
    assert out == [(2.0, 5.0, "클립 안")]


def test_build_filter_complex_contains_trim_and_drawtext():
    fc, v_label, a_label = build_filter_complex(1.5, 40.0, "테스트 문구")
    assert v_label == "[vout]"
    assert a_label == "[aout]"
    assert "trim=start=1.5:end=41.5" in fc
    assert "drawtext=" in fc
    assert "테스트 문구" in fc
    assert "atrim=start=1.5:end=41.5" in fc


def test_build_filter_complex_two_line_title_uses_gold():
    fc, _, _ = build_filter_complex(0.0, 30.0, "주제어\n훅 문장입니다")
    assert "주제어" in fc
    assert "훅 문장입니다" in fc
    assert "fontcolor=gold" in fc


def test_build_filter_complex_includes_caption_cues():
    fc, _, _ = build_filter_complex(
        0.0, 30.0, "제목", captions=[(2.0, 5.0, "자막 문구")]
    )
    assert "자막 문구" in fc
    assert "between(t,2.0,5.0)" in fc


def test_build_filter_complex_includes_top_corner_logos():
    fc, _, _ = build_filter_complex(0.0, 30.0, "제목")
    assert "KBS 1 Radio" in fc
    assert "라디올라" in fc


def test_build_filter_complex_includes_bottom_source_logo():
    fc, _, _ = build_filter_complex(0.0, 30.0, "제목")
    assert "머니올라" in fc


def test_build_filter_complex_uses_custom_source_logo_text():
    fc, _, _ = build_filter_complex(0.0, 30.0, "제목", source_logo_text="경제쑈")
    assert "경제쑈" in fc


def test_build_filter_complex_omits_source_logo_when_none():
    fc, _, _ = build_filter_complex(0.0, 30.0, "제목", source_logo_text=None)
    assert "머니올라" not in fc


def test_build_filter_complex_caption_stays_single_color():
    fc, _, _ = build_filter_complex(
        0.0, 30.0, "제목", captions=[(2.0, 5.0, "구글 웨이모에 어떤 일이 벌어졌냐면 말이죠")]
    )
    assert fc.count("fontcolor=white") >= 3  # title line1 + both logos + caption


def test_build_filter_complex_uses_custom_crop_offset():
    fc, _, _ = build_filter_complex(0.0, 30.0, "제목", crop_x="123", crop_y="45")
    assert "crop=1080:1490:123:45" in fc


def test_build_filter_complex_defaults_to_centered_crop():
    fc, _, _ = build_filter_complex(0.0, 30.0, "제목")
    assert "crop=1080:1490:(in_w-out_w)/2:(in_h-out_h)/2" in fc


def test_face_crop_offset_no_faces_returns_none():
    assert _face_crop_offset([], scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620) is None


def test_face_crop_offset_clamps_to_left_edge():
    # face near the left edge of a much-wider-than-tall scaled frame
    faces = [(100.0, 200.0, 150.0, 150.0)]
    x_off, y_off = _face_crop_offset(
        faces, scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620
    )
    assert x_off == 0
    assert y_off == 0  # scaled_h == canvas_h, no vertical room to crop


def test_face_crop_offset_clamps_to_right_edge():
    faces = [(1700.0, 200.0, 150.0, 150.0)]
    x_off, _ = _face_crop_offset(
        faces, scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620
    )
    assert x_off == 1800  # scaled_w - canvas_w


def test_face_crop_offset_centers_on_face_between_edges():
    faces = [(900.0, 200.0, 150.0, 150.0)]
    x_off, _ = _face_crop_offset(
        faces, scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620
    )
    assert 0 < x_off < 1800


def test_face_crop_offset_weights_toward_larger_face():
    small_face_left = (100.0, 200.0, 50.0, 50.0)
    big_face_right = (1700.0, 200.0, 300.0, 300.0)
    x_off, _ = _face_crop_offset(
        [small_face_left, big_face_right],
        scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620,
    )
    assert x_off > 1400  # pulled toward the bigger (right) face, not the midpoint


def test_render_short_uses_distinct_segment_path_per_candidate(tmp_path):
    # regression test: rendering two different candidates from the same
    # source video must download two different segments, not silently reuse
    # whatever was already sitting at a video_id-only-keyed path
    seen_paths = []

    def fake_download_segment(video_id, start_sec, end_sec, out_path, pad_sec=1.5):
        seen_paths.append(out_path)
        return out_path

    font_path = tmp_path / "font.ttf"
    font_path.write_bytes(b"fake-font")
    work_dir = tmp_path / "work"

    with patch.object(render_module.youtube, "download_segment", side_effect=fake_download_segment), \
         patch.object(render_module, "find_speaker_crop", return_value=("(in_w-out_w)/2", "(in_h-out_h)/2")), \
         patch.object(render_module.subprocess, "run"):
        render_module.render_short(
            video_id="VID123", start_sec=10.0, end_sec=20.0,
            thumbnail_text="a", out_path=tmp_path / "out1.mp4",
            work_dir=work_dir, font_path=str(font_path),
        )
        render_module.render_short(
            video_id="VID123", start_sec=50.0, end_sec=60.0,
            thumbnail_text="b", out_path=tmp_path / "out2.mp4",
            work_dir=work_dir, font_path=str(font_path),
        )

    assert len(seen_paths) == 2
    assert seen_paths[0] != seen_paths[1]
