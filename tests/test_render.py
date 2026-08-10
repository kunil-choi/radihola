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


def test_relative_captions_strips_speaker_change_marker():
    # YouTube auto-captions embed ">>" at speaker changes (see
    # analyze.py's _GUEST_CENTERED_RULE, which reads that same marker) -
    # it must never make it into what's actually burned onto the video.
    segments = [
        Segment(start_sec=0.0, end_sec=5.0, text=">> 그거 하면서부터 확실히 원 달러가"),
        Segment(start_sec=5.0, end_sec=8.0, text="네. >> 그러고"),
    ]
    out = _relative_captions(segments, start_sec=0.0, end_sec=10.0)
    assert out == [
        (0.0, 5.0, "그거 하면서부터 확실히 원 달러가"),
        (5.0, 8.0, "네. 그러고"),
    ]


def test_relative_captions_drops_cue_that_is_only_a_speaker_marker():
    segments = [Segment(start_sec=0.0, end_sec=2.0, text=">>")]
    out = _relative_captions(segments, start_sec=0.0, end_sec=10.0)
    assert out == []


def test_build_filter_complex_contains_trim_and_drawtext():
    # explicit logo_*_image=None keeps this test about the title/trim
    # plumbing regardless of whether real logo assets exist in the repo
    fc, v_label, a_label, extra_inputs = build_filter_complex(
        1.5, 40.0, "테스트 문구", logo_left_image=None, logo_right_image=None
    )
    assert v_label == "[vout]"
    assert a_label == "[aout]"
    assert extra_inputs == []
    assert "trim=start=1.5:end=41.5" in fc
    assert "drawtext=" in fc
    assert "테스트 문구" in fc
    assert "atrim=start=1.5:end=41.5" in fc


def test_build_filter_complex_two_line_title_uses_gold():
    fc, _, _, _ = build_filter_complex(0.0, 30.0, "주제어\n훅 문장입니다")
    assert "주제어" in fc
    assert "훅 문장입니다" in fc
    assert "fontcolor=gold" in fc


def test_build_filter_complex_includes_caption_cues():
    fc, _, _, _ = build_filter_complex(
        0.0, 30.0, "제목", captions=[(2.0, 5.0, "자막 문구")]
    )
    assert "자막 문구" in fc
    assert "between(t,2.0,5.0)" in fc


def test_build_filter_complex_includes_top_left_logo_only():
    # explicit None forces the text-fallback path regardless of whether real
    # logo image assets happen to exist in this checkout of the repo. The
    # top-right corner is intentionally left alone (see LOGO_RIGHT_IMAGE's
    # docstring) so no right-side overlay should appear by default.
    fc, _, _, _ = build_filter_complex(
        0.0, 30.0, "제목", logo_left_image=None, logo_right_image=None
    )
    assert "라디올라" in fc
    assert "overlay=x=main_w-overlay_w" not in fc


def test_build_filter_complex_includes_bottom_source_logo():
    fc, _, _, _ = build_filter_complex(0.0, 30.0, "제목")
    assert "머니올라" in fc


def test_build_filter_complex_uses_custom_source_logo_text():
    # a show name with no entry in SOURCE_LOGO_IMAGES falls back to text
    fc, _, _, _ = build_filter_complex(0.0, 30.0, "제목", source_logo_text="테스트쇼")
    assert "테스트쇼" in fc


def test_build_filter_complex_uses_source_logo_image_when_show_has_one():
    # "경제쇼"/"성공예감 이대호입니다" have real logo art (SOURCE_LOGO_IMAGES) -
    # the image should replace the text entirely, not sit alongside it
    fc, _, _, extra_inputs = build_filter_complex(0.0, 30.0, "제목", source_logo_text="경제쇼")
    assert render_module.SOURCE_LOGO_IMAGES["경제쇼"] in extra_inputs
    assert "text='경제쇼'" not in fc
    assert "[srclogo]" in fc


def test_build_filter_complex_omits_source_logo_when_none():
    fc, _, _, _ = build_filter_complex(0.0, 30.0, "제목", source_logo_text=None)
    assert "머니올라" not in fc


def test_build_filter_complex_title_and_captions_use_display_font():
    fc, _, _, _ = build_filter_complex(
        0.0, 30.0, "제목", captions=[(2.0, 5.0, "자막 문구")],
        font_path="general.ttf", display_font_path="display.ttf",
    )
    assert "drawtext=fontfile=display.ttf:expansion=none:text='제목'" in fc
    assert "drawtext=fontfile=display.ttf:expansion=none:text='자막 문구'" in fc


def test_build_filter_complex_logo_and_source_text_use_general_font():
    fc, _, _, _ = build_filter_complex(
        0.0, 30.0, "제목", logo_left_image=None, source_logo_text="테스트쇼",
        font_path="general.ttf", display_font_path="display.ttf",
    )
    assert "drawtext=fontfile=general.ttf:expansion=none:text='라디올라'" in fc
    assert "drawtext=fontfile=general.ttf:expansion=none:text='테스트쇼'" in fc


def test_build_filter_complex_omits_guest_label_by_default():
    fc, _, _, _ = build_filter_complex(0.0, 30.0, "제목")
    assert "guestbox" not in fc
    assert "guestlabel" not in fc


def test_build_filter_complex_includes_guest_label_when_given():
    fc, _, _, _ = build_filter_complex(
        0.0, 30.0, "제목", guest_label_text="채상욱 상석본부장 / 다이와증권코리아"
    )
    assert "채상욱 상석본부장 / 다이와증권코리아" in fc
    assert "guestbox" in fc
    assert "guestlabel" in fc


def test_build_filter_complex_caption_stays_single_color():
    fc, _, _, _ = build_filter_complex(
        0.0, 30.0, "제목", captions=[(2.0, 5.0, "구글 웨이모에 어떤 일이 벌어졌냐면 말이죠")]
    )
    assert fc.count("fontcolor=white") >= 3  # title line1 + source-credit text + caption


def test_build_filter_complex_caption_uses_full_width_band():
    fc, _, _, _ = build_filter_complex(
        0.0, 30.0, "제목", captions=[(2.0, 5.0, "자막 문구")]
    )
    assert f"drawbox=x=0:y={render_module.CAPTION_BAND_TOP}:w=1080:h={render_module.CAPTION_BAND_H}" in fc


def test_build_filter_complex_falls_back_to_text_logo_when_image_missing(tmp_path):
    missing = tmp_path / "does-not-exist.png"
    fc, _, _, extra_inputs = build_filter_complex(
        0.0, 30.0, "제목", logo_left_image=missing, logo_right_image=missing
    )
    assert extra_inputs == []
    assert "라디올라" in fc  # text fallback still drawn


def test_build_filter_complex_uses_image_overlay_when_logo_file_exists(tmp_path):
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"fake-png-bytes")
    fc, _, _, extra_inputs = build_filter_complex(
        0.0, 30.0, "제목", logo_left_image=logo_path, logo_right_image=None
    )
    assert extra_inputs == [logo_path]
    assert "[1:v]scale=w=" in fc
    assert "overlay=x=" in fc
    assert "라디올라" not in fc  # image overlay replaces the text placeholder


def test_build_filter_complex_crops_transparent_padding_from_real_logo_png(tmp_path):
    # regression test: real logo artwork is often exported on a much bigger
    # transparent canvas than the visible mark, which (left uncropped) shows
    # up as dead space above the logo once overlaid, no matter how tight the
    # overlay margin is. The filter graph must crop to the visible content
    # bbox before scaling.
    from PIL import Image

    logo_path = tmp_path / "padded_logo.png"
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    for x in range(50, 150):
        for y in range(80, 120):
            img.putpixel((x, y), (255, 255, 255, 255))
    img.save(logo_path)

    fc, _, _, extra_inputs = build_filter_complex(
        0.0, 30.0, "제목", logo_left_image=logo_path, logo_right_image=None
    )
    assert extra_inputs == [logo_path]
    assert "[1:v]crop=100:40:50:80,scale=w=" in fc


def test_build_filter_complex_both_logo_images_get_distinct_input_indices(tmp_path):
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    left.write_bytes(b"fake")
    right.write_bytes(b"fake")
    fc, _, _, extra_inputs = build_filter_complex(
        0.0, 30.0, "제목", logo_left_image=left, logo_right_image=right
    )
    assert extra_inputs == [left, right]
    assert "[1:v]scale=w=" in fc
    assert "[2:v]scale=w=" in fc


def test_build_filter_complex_uses_custom_crop_offset():
    fc, _, _, _ = build_filter_complex(0.0, 30.0, "제목", crop_x="123", crop_y="45")
    assert "crop=1080:1620:123:45" in fc


def test_build_filter_complex_defaults_to_centered_crop():
    fc, _, _, _ = build_filter_complex(0.0, 30.0, "제목")
    assert "crop=1080:1620:(in_w-out_w)/2:(in_h-out_h)/2" in fc


def test_face_crop_offset_no_faces_returns_none():
    assert _face_crop_offset(
        [], scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620, src_w=1920
    ) is None


def test_face_crop_offset_clamps_to_left_edge():
    # face near the left edge of a much-wider-than-tall scaled frame
    faces = [(100.0, 200.0, 150.0, 150.0)]
    x_off, y_off = _face_crop_offset(
        faces, scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620, src_w=1920
    )
    assert x_off == 0
    assert y_off == 0  # scaled_h == canvas_h, no vertical room to crop


def test_face_crop_offset_clamps_to_right_edge():
    faces = [(1700.0, 200.0, 150.0, 150.0)]
    x_off, _ = _face_crop_offset(
        faces, scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620, src_w=1920
    )
    assert x_off == 1800  # scaled_w - canvas_w


def test_face_crop_offset_centers_on_face_between_edges():
    faces = [(900.0, 200.0, 150.0, 150.0)]
    x_off, _ = _face_crop_offset(
        faces, scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620, src_w=1920
    )
    assert 0 < x_off < 1800


def test_face_crop_offset_prefers_right_cluster_even_if_smaller():
    # regression test: the studio layout for this show puts the guest
    # (whose commentary the clips are built from) on the right and the host
    # on the left, so the right cluster must win even when the host's face
    # is bigger/closer on a given sampled frame - area is no longer the
    # deciding factor.
    big_face_left = (100.0, 200.0, 300.0, 300.0)
    small_face_right = (1700.0, 200.0, 50.0, 50.0)
    x_off, _ = _face_crop_offset(
        [big_face_left, small_face_right],
        scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620, src_w=1920,
    )
    assert x_off > 1400  # goes with the right (guest) cluster despite being smaller


def test_face_crop_offset_falls_back_to_left_when_right_has_no_faces():
    # a momentary cutaway/single-camera shot with only the host visible
    # should still produce a usable crop instead of no offset at all
    faces = [(100.0, 200.0, 150.0, 150.0)] * 5
    x_off, _ = _face_crop_offset(
        faces, scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620, src_w=1920
    )
    assert x_off == 0


def test_face_crop_offset_split_screen_does_not_land_on_the_seam():
    # regression test: a static two-camera composite (host and guest, each
    # in their own box) puts a face on each side of every sampled frame.
    # Naively averaging all of them lands the crop back on the seam between
    # the two cameras - exactly the bug this clustering avoids.
    faces = [
        (100.0, 200.0, 150.0, 150.0),  # host, left
        (1650.0, 200.0, 170.0, 170.0),  # guest, right
    ] * 5  # same pair detected across several sampled frames
    x_off, _ = _face_crop_offset(
        faces, scale=1.5, canvas_w=1080, canvas_h=1620, scaled_w=2880, scaled_h=1620, src_w=1920
    )
    seam_x_off = (2880 - 1080) / 2  # what a naive full-average would land on
    assert abs(x_off - seam_x_off) > 300  # clearly off the seam, toward the guest's side


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
