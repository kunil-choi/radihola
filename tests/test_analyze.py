from radihola.analyze import _hms_to_sec, _sec_to_hms


def test_hms_roundtrip_under_hour():
    assert _sec_to_hms(_hms_to_sec("08:32")) == "08:32"


def test_hms_roundtrip_over_hour():
    assert _sec_to_hms(_hms_to_sec("01:02:03")) == "01:02:03"


def test_hms_to_sec():
    assert _hms_to_sec("00:08:32") == 512.0
    assert _hms_to_sec("08:32") == 512.0
