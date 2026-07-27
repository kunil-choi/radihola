"""Program definitions for radihola.

NOTE: the ``include``/``exclude`` regex lists below are best-guess patterns for
matching video titles (e.g. "1부", "2부", "브리핑"). YouTube's actual title
format could not be verified while building this (the build environment has
no network access to youtube.com), so before relying on the scheduled
pipeline, run:

    python -m radihola.cli list --program leedaeho
    python -m radihola.cli list --program kyungjeshow

and check that the right videos are picked up / excluded. Adjust the regex
lists here if the real titles look different.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PartRule:
    """Rule describing how to recognize one "part" of a program's daily upload."""

    key: str
    label: str
    # a video title must match at least one of these to belong to this part
    # (empty list = matches everything not excluded elsewhere)
    include: tuple[str, ...] = ()
    # a video title matching any of these is rejected for this part
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProgramConfig:
    key: str
    name: str
    playlist_id: str
    parts: tuple[PartRule, ...]
    # how many days back to look for "today's" upload, in case of late uploads
    lookback_days: int = 2
    # shorts candidates should be within this duration range (seconds)
    min_clip_sec: int = 20
    max_clip_sec: int = 59

    @property
    def playlist_url(self) -> str:
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"


PROGRAMS: dict[str, ProgramConfig] = {
    "leedaeho": ProgramConfig(
        key="leedaeho",
        name="성공예감 이대호입니다",
        playlist_id="PLFnESzVU01TEw0-QDaxnuLcKKoxlMiQpF",
        parts=(
            PartRule(key="part1", label="1부", include=(r"1\s*부",)),
            PartRule(key="part2", label="2부", include=(r"2\s*부",)),
        ),
        # weekday-only show (confirmed via `cli list`: 1부/2부 uploads run
        # Mon-Fri, nothing on Sat/Sun). lookback_days=2 leaves Monday's run
        # unable to reach back to the previous Friday's upload (3 days back);
        # 4 comfortably covers a normal weekend gap plus a day of slack.
        lookback_days=4,
    ),
    "kyungjeshow": ProgramConfig(
        key="kyungjeshow",
        name="경제쇼",
        playlist_id="PLFnESzVU01TG3D5Gj2yrv21vkLiHS7If8",
        parts=(
            PartRule(
                key="main",
                label="본편",
                include=(),
                exclude=(r"브리핑", r"뉴스\s*브리핑", r"모닝\s*브리핑"),
            ),
        ),
        # same channel/weekday schedule as leedaeho; see its lookback_days note.
        lookback_days=4,
    ),
}

# Used for analyze-url: proposing candidates from an arbitrary video URL
# rather than a program's daily upload. Only name/min_clip_sec/max_clip_sec
# matter to analyze.propose_candidates; playlist_id/parts are unused here.
CUSTOM_PROGRAM = ProgramConfig(
    key="custom",
    name="머니올라",
    playlist_id="",
    parts=(),
)


def get_program(key: str) -> ProgramConfig:
    try:
        return PROGRAMS[key]
    except KeyError as e:
        raise SystemExit(
            f"unknown program '{key}'. available: {', '.join(PROGRAMS)}"
        ) from e
