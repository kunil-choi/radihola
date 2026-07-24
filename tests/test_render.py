from radihola.render import build_filter_complex, escape_drawtext


def test_escape_drawtext_colon_and_quote():
    escaped = escape_drawtext("이러다 다 망합니다: '진짜'?")
    assert "\\:" in escaped
    assert "'" not in escaped.replace("’", "")  # straight quote replaced


def test_build_filter_complex_contains_trim_and_drawtext():
    fc, v_label, a_label = build_filter_complex(1.5, 40.0, "테스트 문구")
    assert v_label == "[vout]"
    assert a_label == "[aout]"
    assert "trim=start=1.5:end=41.5" in fc
    assert "drawtext=" in fc
    assert "테스트 문구" in fc
    assert "atrim=start=1.5:end=41.5" in fc
