from pathlib import Path

from radihola.transcript import format_for_prompt, parse_vtt

FIXTURE = Path(__file__).parent / "fixtures" / "rolling_captions.ko.vtt"


def test_parse_vtt_collapses_rolling_duplicates():
    segments = parse_vtt(FIXTURE)
    texts = [s.text for s in segments]
    assert texts == ["안녕하세요", "오늘은", "경제 이야기를", "해보겠습니다"]


def test_parse_vtt_timestamps():
    segments = parse_vtt(FIXTURE)
    assert segments[0].start_sec == 0.0
    assert segments[0].end_sec == 2.0
    assert segments[-1].end_sec == 9.0


def test_format_for_prompt():
    segments = parse_vtt(FIXTURE)
    text = format_for_prompt(segments)
    assert "[00:00-00:02] 안녕하세요" in text
    assert "[00:06-00:09] 해보겠습니다" in text
