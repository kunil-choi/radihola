from types import SimpleNamespace
from unittest.mock import MagicMock

from radihola.analyze import (
    Candidate,
    _closest_boundary,
    _hms_to_sec,
    _sec_to_hms,
    _snap_to_segment_boundaries,
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


def test_closest_boundary_snaps_within_tolerance():
    assert _closest_boundary(1764.0, [1762.76, 1764.679, 1900.0]) == 1764.679


def test_closest_boundary_leaves_unchanged_when_nothing_close():
    assert _closest_boundary(1764.0, [1000.0, 2000.0]) == 1764.0


def test_closest_boundary_leaves_unchanged_with_no_boundaries():
    assert _closest_boundary(1764.0, []) == 1764.0


def test_snap_to_segment_boundaries_fixes_truncation_landing_in_prior_segment():
    # regression test for the exact bug reported: format_for_prompt truncates
    # segment timestamps to whole seconds, so a segment ending at 1764.669s
    # and the next one starting at 1764.679s both display as "29:24" to the
    # model. When the model means to start at the second segment but the
    # chosen "29:24" round-trips to exactly 1764.0, that lands 0.679s inside
    # the *first* segment instead - the clip then opens on a stray fragment
    # of the previous sentence ("...사건이") instead of the intended one
    # ("있었습니다. 뭐냐면...").
    segments = [
        Segment(start_sec=1762.76, end_sec=1764.669, text="우리나라는 이번에 굉장히 큰 사건이"),
        Segment(start_sec=1764.679, end_sec=1767.83, text="있었습니다. 뭐냐면 우리나라 원화"),
    ]
    candidates = [
        Candidate(
            start_sec=1764.0, end_sec=1789.0, title="t", summary="s",
            thumbnail_text="a\nb", reason="r",
        )
    ]
    snapped = _snap_to_segment_boundaries(candidates, segments)
    assert snapped[0].start_sec == 1764.679


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
    assert [c.tier for c in candidates[:5]] == ["hook"] * 5
    assert [c.tier for c in candidates[5:]] == ["substantive"] * 5

    for call in client.messages.create.call_args_list:
        tool = call.kwargs["tools"][0]
        assert tool["input_schema"]["properties"]["candidates"]["minItems"] == 5
        assert tool["input_schema"]["properties"]["candidates"]["maxItems"] == 5

    # the substance tier's system prompt swaps out the hook/virality framing
    # entirely rather than layering substance on top of it
    hook_system = client.messages.create.call_args_list[0].kwargs["system"]
    substance_system = client.messages.create.call_args_list[1].kwargs["system"]
    assert "이탈한다는" in hook_system  # hook-timing rule, only in the hook tier
    assert "이탈한다는" not in substance_system
    assert "조회수를 노리는" in substance_system  # substance-only framing


def test_propose_candidates_uses_unified_duration_cap_for_both_tiers():
    # both tiers now share program.min_clip_sec/max_clip_sec (no more
    # separate long_min_clip_sec/long_max_clip_sec split by tier)
    program = ProgramConfig(
        key="x", name="x", playlist_id="", parts=(), min_clip_sec=15, max_clip_sec=120
    )
    segments = [Segment(start_sec=0, end_sec=100, text="dummy")]

    client = MagicMock()
    client.messages.create.side_effect = [
        _fake_tool_message(5, start_base=0),
        _fake_tool_message(5, start_base=50),
    ]

    propose_candidates(segments, program, "video title", client=client)

    for call in client.messages.create.call_args_list:
        system = call.kwargs["system"]
        assert "15~120초" in system
        assert "120초를 넘기면" in system


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
