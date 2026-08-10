# radihola

KBS 라디오 유튜브 채널 '머니올라'의 쇼츠 코너 **라디올라** 제작을 돕는 자동화 도구.

매일 올라오는 라디오 풀영상(성공예감 이대호입니다 1부/2부, 경제쇼)에서 쇼츠로 만들기 좋은
구간 10개(훅 위주 5개 + 핵심 내용 위주 5개, 모두 2분 이내)를 자동으로 찾아
요약·썸네일 문구와 함께 제안하고, 그중 고른 후보를 실제 세로형(9:16) 쇼츠 mp4로 렌더링해서
다운로드할 수 있게 해준다.

## 어떻게 동작하나

**로컬 웹페이지(webui)를 켜둔 내 컴퓨터에서** 분석·다운로드·렌더링까지 전부 실행된다.
GitHub Actions는 더 이상 이 흐름에 관여하지 않는다 — 클라우드 서버 IP는 유튜브가
봇으로 의심해 자주 차단하는데, 내 컴퓨터(집/회사 네트워크)의 IP로 요청하면 이
문제가 사라진다. webui가 만든 결과(`data/`)는 내 git 계정으로 바로 커밋·푸시된다.

```
[webui: "영상 URL로 쇼츠 후보 뽑기"]
  이대호/경제쇼 풀영상이 올라온 걸 확인하면, 그 영상 URL을 웹페이지에 붙여넣는다
  → (내 컴퓨터에서 직접 실행) 자막 다운로드 (없으면 Whisper로 음성인식)
  → Claude API로 쇼츠 후보 10개 생성 (훅 위주 5개 + 핵심 내용 위주 5개, 모두 2분
    이내, 구간/요약/제목 배너 문구)
  → 후보 구간의 자막(음성인식 결과)에서 오인식된 부분을 문맥에 맞게 교정
  → data/custom/<video_id>/main/candidates.json 커밋·푸시 → 목록 자동 새로고침

[webui]
  브라우저에서 후보 목록/유튜브 미리보기 확인, 시작/끝 시각(인/아웃점)과 제목 배너
  문구를 각 후보마다 직접 수정 가능
  → "쇼츠 만들기" 클릭

[webui: "쇼츠 만들기"]
  (내 컴퓨터에서 직접 실행) 선택된 구간만 다운로드 → 세로형(9:16)으로 크롭 +
  상단 제목 배너 + 하단 자막 합성 → mp4 완성, 웹페이지에서 바로 다운로드 버튼 표시

[GitHub Pages: 다른 사람과 후보만 같이 보고 싶을 때]
  data/의 최신 candidates.json을 정적 페이지로 배포해 누구나 URL로 열람 가능
  (Pages 자체는 분석/렌더링을 수행하지 않고, webui가 커밋한 data/를 보여주기만 한다)
```

## 프로그램 구성

`src/radihola/config.py`에 두 프로그램이 정의되어 있다.

- `leedaeho` — 성공예감 이대호입니다 ([playlist](https://www.youtube.com/playlist?list=PLFnESzVU01TEw0-QDaxnuLcKKoxlMiQpF)), 제목에 "1부"/"2부"가 포함된 영상을 각각 찾는다.
- `kyungjeshow` — 경제쇼 ([playlist](https://www.youtube.com/playlist?list=PLFnESzVU01TG3D5Gj2yrv21vkLiHS7If8)), 제목에 "브리핑"이 포함된 경제뉴스 브리핑 영상은 제외한다.

> **주의**: 이 코드를 만든 빌드 환경은 youtube.com에 네트워크 접근이 불가능해서, 실제
> 영상 제목이 정말 "1부"/"2부"/"브리핑" 같은 패턴을 쓰는지 확인하지 못했다. 처음
> 사용하기 전에 반드시 아래 명령으로 확인하고, 다르면 `config.py`의 `include`/`exclude`
> 정규식을 실제 제목에 맞게 고쳐야 한다.
>
> ```bash
> python -m radihola.cli list --program leedaeho
> python -m radihola.cli list --program kyungjeshow
> ```

## 처음 설정하기

### 1. 로컬 실행 환경 준비

webui가 분석·렌더링을 전부 내 컴퓨터에서 실행하므로, 이 레포를 clone한 컴퓨터에
아래가 준비되어 있어야 한다.

- Python 3.11+, `ffmpeg`, 한글 폰트(`fonts-nanum` 등)
- 이 레포에 대해 `git push`가 정상 동작하는 git 로그인 상태 (후보 생성 결과를
  자동으로 커밋·푸시하기 때문)
- Claude API 키 (`ANTHROPIC_API_KEY`) — [console.anthropic.com](https://console.anthropic.com)에서 발급

> **Windows**: 기본 자막/제목 폰트 경로(`NanumGothicBold`)는 리눅스 전용이라, Windows에서는
> `webui/.env`에 `RADIHOLA_FONT=C:/Windows/Fonts/malgunbd.ttf` (맑은 고딕 볼드, 대부분의
> 한글 Windows에 기본 설치되어 있음) 를 추가해야 자막/제목이 정상적으로 렌더링된다.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp webui/.env.example webui/.env
# webui/.env를 열어 ANTHROPIC_API_KEY를 채운다
```

`webui/.env`는 `.gitignore`에 포함되어 커밋되지 않는다.

#### YouTube가 "Sign in to confirm you're not a bot"으로 막을 때

클라우드 서버 IP는 유튜브가 봇으로 의심해서 차단하는 경우가 흔한데, 집/회사
네트워크에서 직접 실행하는 이 방식은 대부분 이 문제를 피해간다. 코드에 기본으로
android/tv 클라이언트로 우회하는 처리도 들어있다. 그래도 막히면 로그인된 브라우저의
쿠키를 넘겨주는 방법으로 해결한다:

1. 크롬/엣지에 "Get cookies.txt LOCALLY" 같은 확장 프로그램을 설치
2. 유튜브에 로그인된 상태로 youtube.com 접속 → 확장 프로그램 아이콘 클릭 → 쿠키를 내보내기(Export)
3. 내려받은 `cookies.txt` 파일을 컴퓨터 아무 곳에나 저장 (예: `~/youtube-cookies.txt`)
4. `webui/.env`에 `YTDLP_COOKIES_FILE=/절대/경로/youtube-cookies.txt` 추가

> 이 파일은 내 유튜브 로그인 정보이므로 저장소에 커밋하면 안 된다 (`.env`와 마찬가지로
> 레포 바깥 경로에 두는 걸 권장). 며칠 지나면 다시 만료될 수 있으니, 다시
> "Sign in to confirm you're not a bot" 에러가 뜨면 1~4단계로 새로 받으면 된다.

### 2. 로컬 리뷰 웹페이지 실행

```bash
uvicorn webui.server:app --reload --port 8787
# http://localhost:8787 접속
```

Windows에서는 저장소 루트의 `start-webui.bat`을 더블클릭해도 된다 (가상환경 활성화 +
서버 실행을 한 번에 해준다). 매번 열기 번거로우면 이 파일의 바로가기를 바탕화면에
만들어두면 편하다.

"영상 URL로 쇼츠 후보 뽑기"와 "이 후보로 쇼츠 만들기" 버튼을 누르면 이 서버가 떠 있는
컴퓨터에서 바로 분석/렌더링이 실행된다 (GitHub Actions를 거치지 않는다). 완료되면
후보 목록은 자동 새로고침되고, 렌더링된 mp4는 페이지에서 바로 다운로드할 수 있다.

### 3. (선택) GitHub 저장소 설정 — Pages로 후보 공유, 수동 Actions 실행

로컬 webui 없이 다른 사람과 후보만 같이 보고 싶다면 GitHub Pages(`pages.yml`)를 쓸 수
있다. 이건 webui가 커밋한 `data/`를 정적 페이지로 보여주기만 하고 별도 실행 환경
설정이 필요없다. `daily-analyze.yml`/`analyze-url.yml`/`render-short.yml`도 Actions
탭에 남아있어 수동 실행은 가능하지만, 클라우드 IP 차단 문제 때문에 주 사용 흐름은
아니다 (필요하면 `Settings → Secrets and variables → Actions`에 `ANTHROPIC_API_KEY`를
등록해야 동작한다).

## CLI로 직접 쓰기 (webui 없이)

```bash
# 오늘자 후보 생성 (로컬에서 직접 실행할 때, ANTHROPIC_API_KEY 필요)
python -m radihola.cli analyze --program leedaeho

# 임의의 영상 URL에서 후보 생성 (프로그램/일정에 안 묶인 영상도 가능)
python -m radihola.cli analyze-url --url https://www.youtube.com/watch?v=VIDEO_ID

# 특정 구간을 쇼츠로 렌더링
python -m radihola.cli render \
  --video-id VIDEO_ID --start 512 --end 556 \
  --thumbnail-text "이러다 다 망합니다" --out output/short.mp4

# candidates.json에서 특정 후보 id를 골라 렌더링
python -m radihola.cli render \
  --candidate-file data/leedaeho/2026-07-24/part1/candidates.json --candidate-id 3 \
  --out output/short.mp4
```

로컬에서 돌리려면 `ffmpeg`과 한글 폰트(예: `fonts-nanum`)가 설치되어 있어야 한다.

## 자막(스크립트) 소스

유튜브에 이미 있는 자막(수동/자동)을 우선 사용하고, 없는 영상만 `faster-whisper`로
로컬 음성인식을 돌린다 (`src/radihola/transcript.py`). 자막 언어는 기본 `ko`.

## 쇼츠 영상 스타일

`src/radihola/render.py`: 1080x1920 캔버스 상단에 검은 제목 배너(1줄 흰색 키워드 +
2줄 강조색 훅 문구, `thumbnail_text`를 줄바꿈으로 구분)와 좌/우 상단 자체 로고(KBS 1
Radio / 라디올라 — `assets/logos/`에 이미지 파일이 있으면 그 이미지를, 없으면 텍스트를
표시)를 넣고, 그 아래로 원본 영상을 얼굴 인식으로 화자 위치를 맞춰 화면 전체 너비에
꽉 차게 크롭해서 배치한다. 화면 맨 아래에는 검은 띠를 하나 더 두고 이 클립이 어느
원본 방송(성공예감 이대호입니다 / 경제쇼)에서 나온 건지 영상 제목으로 추론해서
표시하며, 그 바로 위에는 화면 전체 너비의 어두운 띠 배경 위에 굵은 흰색 대형 자막을
대사 타이밍에 맞춰 자동으로 표시한다. 이 자막은 음성인식 오류(발음이 비슷한 단어로
잘못 받아쓴 부분)를 Claude로 한 번 교정한 뒤 사용한다 (`analyze.correct_caption_errors`).
위치/폰트/색상 등은 해당 파일 상단 상수에서 조정할 수 있다.

## 테스트

```bash
pip install -r requirements.txt pytest
pytest
```

유튜브 다운로드·Claude API 호출처럼 외부 네트워크가 필요한 부분은 유닛 테스트로
검증할 수 없어서, 정규식 매칭/자막 파싱/ffmpeg 필터 그래프 구성 같은 순수 로직만
테스트로 커버했다. 전체 파이프라인은 GitHub Actions 실행 결과로 확인한다.
