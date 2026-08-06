from types import SimpleNamespace
from unittest.mock import MagicMock

from radihola.analyze import (
    _hms_to_sec,
    _sec_to_hms,
    correct_caption_errors,
    extract_guest_info,
    propose_candidates,
)
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


def test_propose_candidates_generates_three_tiers():
    program = ProgramConfig(key="x", name="x", playlist_id="", parts=())
    segments = [Segment(start_sec=0, end_sec=100, text="dummy")]

    client = MagicMock()
    client.messages.create.side_effect = [
        _fake_tool_message(5, start_base=0),
        _fake_tool_message(5, start_base=50),
        _fake_tool_message(5, start_base=100),
    ]

    candidates = propose_candidates(segments, program, "video title", client=client)

    assert len(candidates) == 15
    assert client.messages.create.call_count == 3
    assert [c.tier for c in candidates[:5]] == ["single_speaker_short"] * 5
    assert [c.tier for c in candidates[5:10]] == ["flexible_long"] * 5
    assert [c.tier for c in candidates[10:]] == ["substantive_long"] * 5

    for call in client.messages.create.call_args_list:
        tool = call.kwargs["tools"][0]
        assert tool["input_schema"]["properties"]["candidates"]["minItems"] == 5
        assert tool["input_schema"]["properties"]["candidates"]["maxItems"] == 5

    # the substance tier's system prompt swaps out the hook/virality framing
    # entirely rather than layering substance on top of it
    hook_system = client.messages.create.call_args_list[0].kwargs["system"]
    substance_system = client.messages.create.call_args_list[2].kwargs["system"]
    assert "이탈한다는" in hook_system  # hook-timing rule, only in the hook tiers
    assert "이탈한다는" not in substance_system
    assert "조회수를 노리는" in substance_system  # substance-only framing


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


def test_extract_guest_info_empty_description_short_circuits():
    client = MagicMock()
    assert extract_guest_info("제목", None, client=client) == ""
    assert extract_guest_info("제목", "", client=client) == ""
    client.messages.create.assert_not_called()


def test_extract_guest_info_formats_name_title_org():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                input={"found": True, "name": "김은비", "title": "변호사", "org": "손해보험협회"},
            )
        ]
    )
    assert extract_guest_info("제목", "설명", client=client) == "김은비 변호사 / 손해보험협회"


def test_extract_guest_info_omits_missing_title_or_org():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"found": True, "name": "김은비"})]
    )
    assert extract_guest_info("제목", "설명", client=client) == "김은비"


def test_extract_guest_info_returns_empty_when_not_found():
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"found": False})]
    )
    assert extract_guest_info("제목", "설명", client=client) == ""


def test_extract_guest_info_falls_back_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    assert extract_guest_info("제목", "설명", client=client) == ""
