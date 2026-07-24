from radihola.config import PROGRAMS
from radihola.youtube import matches_part

LEEDAEHO = PROGRAMS["leedaeho"]
KYUNGJESHOW = PROGRAMS["kyungjeshow"]


def test_leedaeho_part1_matches():
    rule = next(r for r in LEEDAEHO.parts if r.key == "part1")
    assert matches_part("[성공예감 이대호입니다] 1부 다시듣기 (7/24)", rule)
    assert not matches_part("[성공예감 이대호입니다] 2부 다시듣기 (7/24)", rule)


def test_leedaeho_part2_matches():
    rule = next(r for r in LEEDAEHO.parts if r.key == "part2")
    assert matches_part("[성공예감 이대호입니다] 2부 다시듣기 (7/24)", rule)
    assert not matches_part("[성공예감 이대호입니다] 1부 다시듣기 (7/24)", rule)


def test_leedaeho_unrelated_title_matches_neither():
    for rule in LEEDAEHO.parts:
        assert not matches_part("성공예감 이대호입니다 하이라이트 모음", rule)


def test_kyungjeshow_excludes_briefing():
    rule = KYUNGJESHOW.parts[0]
    assert matches_part("경제쇼 7월 24일 방송", rule)
    assert not matches_part("경제쇼 모닝 브리핑 7월 24일", rule)
    assert not matches_part("경제뉴스 브리핑 (7/24)", rule)
