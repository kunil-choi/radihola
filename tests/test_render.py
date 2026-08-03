from radihola.render import (
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


def test_build_filter_complex_includes_logo_placeholders():
    fc, _, _ = build_filter_complex(0.0, 30.0, "제목")
    assert "KBS 1 Radio" in fc
    assert "라디올리" in fc
