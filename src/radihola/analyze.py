"""Ask Claude to propose shorts candidates from a timestamped transcript."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass

import anthropic

from .config import ProgramConfig
from .transcript import Segment, format_for_prompt

MODEL = os.environ.get("RADIHOLA_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT_TEMPLATE = """\
너는 KBS 라디오 유튜브 채널 '머니올라'의 쇼츠 코너 '라디올라' 담당 PD를 돕는 편집 보조야.
매일 올라오는 라디오 방송 풀영상에서, 쇼츠로 잘라 올리기 좋은 구간을 찾아내는 게 네 역할이다.

지금 요청하는 건 아래 조건에 맞는 구간 정확히 {count}개다.

좋은 후보의 기준:
- 길이는 반드시 {max_sec}초를 넘기면 안 된다 ({min_sec}~{max_sec}초를 목표로 한다). {max_sec}초
  안에서 문장이 자연스럽게 시작되고 끝나는 지점을 찾아라: 새로운 문장/화제가 막 시작하는 지점에서
  시작하고, 그 발언이 결론까지 자연스럽게 끝나는 지점에서 끝내라. 문장 중간에서 시작하거나
  끊기면 안 된다. 내용이 길어서 {max_sec}초 안에 못 담는다면 그 구간은 포기하고, 더 짧고 그
  자체로 완결된 다른 구간을 찾아라. 그 구간만 봐도 무슨 얘기인지 완전히 이해가 되어야 한다
  (앞뒤 맥락 설명 없이도 독립적으로 말이 될 것).
- 시작 지점과 끝 지점 모두 그 구간의 핵심 주제와 직접 관련된 발언이어야 한다. 시작을 이전
  화제의 꼬리(마무리 멘트, "아무튼", "그래서" 같은 전환어만 있는 줄)에서 잡거나, 끝을 다음
  화제로 넘어가는 도입부(다른 주제를 막 꺼내는 줄)에서 끊으면 안 된다 — 주제와 무관한 앞뒤
  내용이 섞이면 그 줄은 버리고, 핵심 주제에 해당하는 발언만으로 시작/끝 경계를 다시 잡아라.
- 시작/끝 시각은 반드시 주어진 대본의 타임스탬프 구간 경계와 일치시켜라 (타임스탬프 구간 중간 지점을
  임의로 잘라 쓰지 말 것).
{speaker_rule}
- 훅(궁금증을 유발하거나 임팩트 있는 발언)이 반드시 시작 3초 안에 있어야 하는 건 아니다.
  영상 상단에 thumbnail_text로 만든 제목 배너가 재생 내내 화면에 떠 있어서 그 자체로
  시청자를 붙잡아주기 때문이다. 다만 실제 쇼츠 시청자의 절반 이상은 처음 몇 초 안에
  이탈한다는 게 알려져 있으므로("훅"이 늦을수록 이탈 위험이 커진다), 구간 전체 길이의
  앞쪽 1/3 지점 안에는 훅이 나와야 하고, 그중에서도 최대한 앞쪽에 있는 구간을 우선한다.
- 최근 한국/글로벌 경제 상황에서 화제가 되고 있는 이슈(금리, 환율, 부동산, 특정 기업 실적,
  고용/구조조정, AI 투자 논쟁 등)를 다루는 구간을 우선한다. 네가 알고 있는 최신 경제
  이슈와 이 영상에서 실제로 논의되는 내용이 겹치는지 판단해서 반영해라.
- 경제/재테크 유튜브 쇼츠가 조회수를 잘 받는 데는 공통된 패턴이 있다: (a) 구체적인 금액·
  퍼센트 수치가 들어간 발언, (b) "내 월급", "내 집값", "내 연금"처럼 시청자 개인의 자산·
  생활에 직접 영향을 준다고 느껴지는 내용, (c) 전문가들 사이의 의견 충돌이나 예상을
  뒤엎는 반전, (d) "그래서 지금 뭘 해야 하나"에 대한 실용적 결론. 이런 요소가 있는 구간을
  단정적이거나 논쟁적이거나 의외성 있는 발언, 웃긴 순간과 함께 우선한다.
- 같은 주제를 반복하는 후보끼리는 피하고, 서로 다른 순간 {count}개를 고른다.
- thumbnail_text는 영상 상단 제목 배너에 들어갈 문구로, 정확히 두 줄을 줄바꿈(\n) 하나로 구분해서 써라.
  1번째 줄: 주제를 압축한 짧은 키워드/명사구 (5~10자, 흰색으로 표시됨)
  2번째 줄: 궁금증을 유발하는 질문형 또는 임팩트 있는 훅 문장 (8~14자, 강조색으로 표시됨)
  두 줄 다 자극적이되 실제 발언 내용과 어긋나지 않아야 한다. 예: "로봇택시\n취객은 누가 깨울까?"

주어지는 대본은 "[시작-끝] 텍스트" 형식의 타임스탬프 붙은 줄들이다. 이걸 그대로 참고해서 시작/끝 시각을 고를 것.
정확히 {count}개의 후보를 제시해라.
"""

_GUEST_CENTERED_RULE = """\
- 대본에서 화자가 바뀌는 지점은 ">>"로 표시되어 있다. 누가 진행자(짧게 질문하거나
  맞장구치는 쪽)이고 누가 출연자(실제로 분석·설명·의견을 길게 이야기하는 쪽)인지 대본
  내용으로 판단해라. 렌더링 화면은 클립 내내 출연자 얼굴로 고정되고 진행자가 말할 때도
  화면은 바뀌지 않은 채 목소리만 나오므로, 이를 고려해서 아래 세 가지 패턴 중 하나로
  구간을 골라라 (섞어서 판단해도 된다):
  (1) 출연자 혼자 끊김 없이 말하는 구간(">>"가 전혀 없음). 길고 완결된 발언이 있다면
      이 패턴을 우선한다.
  (2) 출연자의 발언만으로는 무슨 내용인지 이해가 안 되는 경우, 그 발언을 이끌어낸 진행자의
      바로 앞 질문부터 포함한다 — 구간의 시작을 그 진행자 질문이 시작되는 지점으로 잡는다.
  (3) 출연자가 길게 이야기하는 도중에 진행자가 짧게 맞장구를 치거나 중간 질문을 던지는
      정도라면 그 부분을 잘라내지 말고 그대로 포함한다.
  다만 어느 패턴이든 구간 전체 발화 시간의 대부분은 출연자여야 한다 — 진행자가 여러
  문장에 걸쳐 길게 말하는 인터뷰 도입부나, 진행자 발언이 구간의 절반 이상을 차지하는
  구간은 고르지 마라.\
"""

# each analysis produces two tiers of 5 candidates each, differing only in
# target duration - both are guest-centered (see _GUEST_CENTERED_RULE): the
# render crop stays fixed on the guest's side of frame for the whole clip,
# so brief host lines are fine as audio-only, but the host can never be the
# majority of the spoken content
CANDIDATE_TIERS = (
    ("single_speaker_short", 5, _GUEST_CENTERED_RULE),
    ("flexible_long", 5, _GUEST_CENTERED_RULE),
)

TIER_LABELS = {
    "single_speaker_short": "출연자 중심 발언 · 30초 이내",
    "flexible_long": "출연자 중심 발언 · 1분 30초 이내",
}


@dataclass
class Candidate:
    start_sec: float
    end_sec: float
    title: str
    summary: str
    thumbnail_text: str
    reason: str
    tier: str = ""

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


def _candidate_tool(count: int) -> dict:
    return {
        "name": "propose_shorts_candidates",
        "description": f"라디오 풀영상에서 쇼츠로 만들기 좋은 {count}개 구간을 제안한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_hms": {
                                "type": "string",
                                "description": (
                                    "구간 시작 시각, MM:SS 또는 HH:MM:SS. 반드시 새 문장/화제가 "
                                    "시작하는 대본 타임스탬프 경계와 일치시킬 것."
                                ),
                            },
                            "end_hms": {
                                "type": "string",
                                "description": (
                                    "구간 끝 시각, MM:SS 또는 HH:MM:SS. 반드시 그 발언이 자연스럽게 "
                                    "끝나는 대본 타임스탬프 경계와 일치시킬 것 (문장 중간에 끊지 말 것)."
                                ),
                            },
                            "title": {"type": "string", "description": "짧은 내부 제목"},
                            "summary": {
                                "type": "string",
                                "description": "이 구간에서 실제로 어떤 이야기가 나오는지 2~3문장 요약",
                            },
                            "thumbnail_text": {
                                "type": "string",
                                "description": (
                                    "영상 상단 제목 배너 문구. 정확히 두 줄, 그 사이를 \\n 하나로 구분: "
                                    "1번째 줄은 짧은 주제 키워드(5~10자), 2번째 줄은 훅이 되는 질문/임팩트 문장"
                                    "(8~14자). 예: '로봇택시\\n취객은 누가 깨울까?'"
                                ),
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


def _propose_candidates_for_tier(
    client: anthropic.Anthropic,
    transcript_text: str,
    program: ProgramConfig,
    video_title: str,
    tier: str,
    count: int,
    speaker_rule: str,
) -> list[Candidate]:
    min_sec, max_sec = (
        (program.min_clip_sec, program.max_clip_sec)
        if tier == "single_speaker_short"
        else (program.long_min_clip_sec, program.long_max_clip_sec)
    )
    system = SYSTEM_PROMPT_TEMPLATE.format(
        count=count, min_sec=min_sec, max_sec=max_sec, speaker_rule=speaker_rule
    )
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system,
        tools=[_candidate_tool(count)],
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
                tier=tier,
            )
        )
    return candidates


def propose_candidates(
    segments: list[Segment],
    program: ProgramConfig,
    video_title: str,
    client: anthropic.Anthropic | None = None,
) -> list[Candidate]:
    client = client or anthropic.Anthropic()
    transcript_text = format_for_prompt(segments)

    candidates: list[Candidate] = []
    for tier, count, speaker_rule in CANDIDATE_TIERS:
        candidates.extend(
            _propose_candidates_for_tier(
                client, transcript_text, program, video_title, tier, count, speaker_rule
            )
        )
    return candidates


def candidate_to_dict(c: Candidate) -> dict:
    d = asdict(c)
    d["start_hms"] = c.start_hms
    d["end_hms"] = c.end_hms
    d["tier_label"] = TIER_LABELS.get(c.tier, c.tier)
    return d


CAPTION_CORRECTION_TOOL = {
    "name": "correct_captions",
    "description": "제공된 자막 문장들에서 음성인식 오류로 보이는 부분만 문맥에 맞게 교정한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "corrected": {
                "type": "array",
                "description": "입력과 정확히 같은 개수·순서로 교정된 문장을 반환한다.",
                "items": {"type": "string"},
            }
        },
        "required": ["corrected"],
    },
}


def correct_caption_errors(texts: list[str], client: anthropic.Anthropic | None = None) -> list[str]:
    """Best-effort: ask Claude to fix likely speech-recognition mishearings in
    a batch of caption lines, preserving meaning/count/order. Falls back to
    the original texts on any failure (wrong count, API error, etc.) - this
    is a polish step, never worth breaking the pipeline over.
    """
    if not texts:
        return texts
    client = client or anthropic.Anthropic()
    numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(texts))
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=(
                "다음은 라디오 방송을 자동 음성인식(STT)으로 받아쓴 자막 문장들이다. "
                "발음이 비슷한 다른 단어로 잘못 인식되어 문맥상 말이 안 되는 부분이 "
                "있을 수 있다. 그런 오류만 문맥에 맞게 자연스러운 한국어로 고쳐라. "
                "이미 맞는 문장은 절대 건드리지 말고, 뜻이나 어투를 임의로 바꾸지 마라 "
                "(오타/오인식 교정이지 문장 재작성이 아니다). 입력과 정확히 같은 "
                "개수·순서로 반환해야 한다."
            ),
            tools=[CAPTION_CORRECTION_TOOL],
            tool_choice={"type": "tool", "name": "correct_captions"},
            messages=[{"role": "user", "content": numbered}],
        )
        tool_use = next(b for b in message.content if b.type == "tool_use")
        corrected = tool_use.input["corrected"]
        if len(corrected) != len(texts):
            return texts
        return corrected
    except Exception:
        return texts
