from types import SimpleNamespace
from unittest.mock import MagicMock

from radihola.analyze import _hms_to_sec, _sec_to_hms, correct_caption_errors, propose_candidates
from radihola.config import ProgramConfig
from radihola.transcript import Segment


def test_hms_roundtrip_under_hour():
    assert _sec_to_hms(_hms_to_sec("08:32")) == "08:32"


def test_hms_roundtrip_over_hour():
    assert _sec_to_hms(_hms_to_sec("01:02:03")) == "01:02:03"


def test_hms_to_sec():
    assert _hms_to_sec("00:08:32") == 512.0
    assert _hms_to_sec("08:32") == 512.0


def _fake_tool_message(count: int, start_base: int = 0):
    candidates = [
        {
            "start_hms": f"00:{i:02d}",
            "end_hms": f"00:{i + 5:02d}",
            "title": f"t{i}",
            "summary": "s",
            "thumbnail_text": "a\nb",
            "reason": "r",
        }
        for i in range(start_base, start_base + count)
    ]
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"candidates": candidates})])


def test_propose_candidates_generates_two_tiers():
    program = ProgramConfig(key="x", name="x", playlist_id="", parts=())
    segments = [Segment(start_sec=0, end_sec=100, text="dummy")]

    client = MagicMock()
    client.messages.create.side_effect = [
        _fake_tool_message(5, start_base=0),
        _fake_tool_message(5, start_base=50),
    ]

    candidates = propose_candidates(segments, program, "video title", client=client)

    assert len(candidates) == 10
    assert client.messages.create.call_count == 2
    assert [c.tier for c in candidates[:5]] == ["single_speaker_short"] * 5
    assert [c.tier for c in candidates[5:]] == ["flexible_long"] * 5

    for call in client.messages.create.call_args_list:
        tool = call.kwargs["tools"][0]
        assert tool["input_schema"]["properties"]["candidates"]["minItems"] == 5
        assert tool["input_schema"]["properties"]["candidates"]["maxItems"] == 5


def test_correct_caption_errors_empty_input_short_circuits():
    client = MagicMock()
    assert correct_caption_errors([], client=client) == []
    client.messages.create.assert_not_called()


def test_correct_caption_errors_returns_corrected_texts():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"corrected": ["교정1", "교정2"]})]
    )
    result = correct_caption_errors(["오류1", "오류2"], client=client)
    assert result == ["교정1", "교정2"]


def test_correct_caption_errors_falls_back_on_count_mismatch():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"corrected": ["교정1"]})]
    )
    original = ["오류1", "오류2"]
    assert correct_caption_errors(original, client=client) == original


def test_correct_caption_errors_falls_back_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    original = ["오류1", "오류2"]
    assert correct_caption_errors(original, client=client) == original
