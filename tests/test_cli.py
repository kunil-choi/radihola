from radihola.cli import build_parser


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
