"""Ask Claude to propose shorts candidates from a timestamped transcript."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass

import anthropic

from .config import ProgramConfig
from .transcript import Segment, format_for_prompt

MODEL = os.environ.get("RADIHOLA_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """\
너는 KBS 라디오 유튜브 채널 '머니올라'의 쇼츠 코너 '라디올라' 담당 PD를 돕는 편집 보조야.
매일 올라오는 라디오 방송 풀영상에서, 쇼츠로 잘라 올리기 좋은 구간을 찾아내는 게 네 역할이다.

좋은 후보의 기준:
- 길이는 {min_sec}~{max_sec}초 사이. 문장이 중간에 끊기지 않고, 그 구간만 봐도 무슨 얘기인지 이해가 되어야 한다 (앞뒤 맥락 설명 없이도 독립적으로 말이 될 것).
- 시작 3초 안에 훅(궁금증을 유발하거나 임팩트 있는 발언)이 있어야 한다.
- 단정적이거나 논쟁적이거나 의외성 있는 발언, 구체적인 숫자/전망, 실용적인 조언, 웃긴 순간 등 클릭을 부르는 내용을 우선한다.
- 같은 주제를 반복하는 후보끼리는 피하고, 서로 다른 순간 10개를 고른다.
- thumbnail_text는 실제 유튜브 쇼츠 썸네일에 올라갈 한 줄 문구다. 자극적이되 실제 발언 내용과 어긋나지 않아야 하며, 10~20자 내외로 짧고 강하게 쓴다.

주어지는 대본은 "[시작-끝] 텍스트" 형식의 타임스탬프 붙은 줄들이다. 이걸 그대로 참고해서 시작/끝 시각을 고를 것.
정확히 10개의 후보를 제시해라.
"""


@dataclass
class Candidate:
    start_sec: float
    end_sec: float
    title: str
    summary: str
    thumbnail_text: str
    reason: str

    @property
    def start_hms(self) -> str:
        return _sec_to_hms(self.start_sec)

    @property
    def end_hms(self) -> str:
        return _sec_to_hms(self.end_sec)


def _sec_to_hms(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _hms_to_sec(hms: str) -> float:
    parts = [float(p) for p in hms.strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


CANDIDATE_TOOL = {
    "name": "propose_shorts_candidates",
    "description": "라디오 풀영상에서 쇼츠로 만들기 좋은 10개 구간을 제안한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 10,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "start_hms": {
                            "type": "string",
                            "description": "구간 시작 시각, MM:SS 또는 HH:MM:SS",
                        },
                        "end_hms": {
                            "type": "string",
                            "description": "구간 끝 시각, MM:SS 또는 HH:MM:SS",
                        },
                        "title": {"type": "string", "description": "짧은 내부 제목"},
                        "summary": {
                            "type": "string",
                            "description": "이 구간에서 실제로 어떤 이야기가 나오는지 2~3문장 요약",
                        },
                        "thumbnail_text": {
                            "type": "string",
                            "description": "쇼츠 썸네일에 올릴 임팩트 있는 한 줄 문구 (10~20자 내외)",
                        },
                        "reason": {
                            "type": "string",
                            "description": "왜 이 구간이 쇼츠로 매력적인지",
                        },
                    },
                    "required": [
                        "start_hms",
                        "end_hms",
                        "title",
                        "summary",
                        "thumbnail_text",
                        "reason",
                    ],
                },
            }
        },
        "required": ["candidates"],
    },
}


def propose_candidates(
    segments: list[Segment],
    program: ProgramConfig,
    video_title: str,
    client: anthropic.Anthropic | None = None,
) -> list[Candidate]:
    client = client or anthropic.Anthropic()
    transcript_text = format_for_prompt(segments)
    system = SYSTEM_PROMPT.format(
        min_sec=program.min_clip_sec, max_sec=program.max_clip_sec
    )
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system,
        tools=[CANDIDATE_TOOL],
        tool_choice={"type": "tool", "name": "propose_shorts_candidates"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"프로그램: {program.name}\n"
                    f"영상 제목: {video_title}\n\n"
                    f"대본:\n{transcript_text}"
                ),
            }
        ],
    )

    tool_use = next(b for b in message.content if b.type == "tool_use")
    raw_candidates = tool_use.input["candidates"]

    candidates: list[Candidate] = []
    for c in raw_candidates:
        start = _hms_to_sec(c["start_hms"])
        end = _hms_to_sec(c["end_hms"])
        if end <= start:
            continue
        candidates.append(
            Candidate(
                start_sec=start,
                end_sec=end,
                title=c["title"],
                summary=c["summary"],
                thumbnail_text=c["thumbnail_text"],
                reason=c["reason"],
            )
        )
    return candidates


def candidate_to_dict(c: Candidate) -> dict:
    d = asdict(c)
    d["start_hms"] = c.start_hms
    d["end_hms"] = c.end_hms
    return d
