from radihola.cli import _guess_show_name, build_parser


def test_list_command_parses():
    parser = build_parser()
    args = parser.parse_args(["list", "--program", "leedaeho"])
    assert args.program == "leedaeho"


def test_render_command_parses():
    parser = build_parser()
    args = parser.parse_args(
        [
            "render",
            "--video-id",
            "abc123",
            "--start",
            "1.5",
            "--end",
            "40",
            "--thumbnail-text",
            "hi",
            "--out",
            "/tmp/out.mp4",
        ]
    )
    assert args.video_id == "abc123"
    assert args.start == 1.5


def test_guess_show_name_leedaeho():
    assert _guess_show_name("성공예감 이대호입니다 2부 - 8월 5일") == "성공예감 이대호입니다"


def test_guess_show_name_kyungjeshow():
    assert _guess_show_name("경제쇼 8월 5일 방송분") == "경제쑈"


def test_guess_show_name_falls_back_to_custom_program_name():
    assert _guess_show_name("전혀 관계없는 제목") == "머니올라"
