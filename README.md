# radihola

KBS 라디오 유튜브 채널 '머니올라'의 쇼츠 코너 **라디올라** 제작을 돕는 자동화 도구.

매일 올라오는 라디오 풀영상(성공예감 이대호입니다 1부/2부, 경제쇼)에서 쇼츠로 만들기 좋은
구간 10개를 자동으로 찾아 요약·썸네일 문구와 함께 제안하고, 그중 고른 후보를 실제
세로형(9:16) 쇼츠 mp4로 렌더링해서 다운로드할 수 있게 해준다.

## 어떻게 동작하나

전체 다운로드·렌더링은 **GitHub Actions**에서 실행되고, 후보를 보고 고르는 화면만
**로컬 웹페이지**로 띄운다.

```
[주 사용 흐름 — on-demand 실행: analyze-url.yml (webui의 "영상 URL로 쇼츠 후보 뽑기")]
  이대호/경제쇼 풀영상이 올라온 걸 확인하면, 그 영상 URL을 웹페이지에 붙여넣는다
  → 자막 다운로드 (없으면 Whisper로 음성인식)
  → Claude API로 쇼츠 후보 10개 생성 (구간, 요약, 제목 배너 문구)
  → data/custom/<video_id>/main/candidates.json 커밋 → webui가 자동 새로고침

[로컬/Pages: webui]
  최신 candidates.json 반영
  → 브라우저에서 후보 목록/유튜브 미리보기 확인, 제목 배너 문구 수정
  → "쇼츠 만들기" 클릭

[on-demand 실행: render-short.yml]
  선택된 구간만 다운로드 → 세로형(9:16)으로 크롭 + 상단 제목 배너 + 하단 자막 합성
  → mp4를 Actions 아티팩트로 업로드

[로컬/Pages: webui]
  실행 완료를 감지해 아티팩트를 내려받아 브라우저에서 다운로드 버튼 표시 (또는 실행 링크로 이동)

[선택 사용 — 수동 실행: daily-analyze.yml]
  playlist에서 오늘자 영상을 자동으로 찾아서 위와 같은 방식으로 분석.
  영상 ~20개씩 훑는 만큼 유튜브 요청이 많아 YOUTUBE_COOKIES가 금방 만료되는
  경향이 있어 예약 실행은 꺼두었다. 필요할 때 Actions 탭에서 수동으로만 돌린다.
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

### 1. GitHub 저장소 설정

- **Secrets**: `Settings → Secrets and variables → Actions`에서 `ANTHROPIC_API_KEY`를 등록한다 (daily-analyze가 Claude API로 후보를 생성하는 데 사용).
- **워크플로우 쓰기 권한**: `Settings → Actions → General → Workflow permissions`에서
  "Read and write permissions"를 선택해야 daily-analyze가 `data/`를 커밋·푸시할 수 있다.
- 세 워크플로우 모두 GitHub Actions 탭에서 확인 가능:
  - `analyze-url.yml` — 웹페이지의 "영상 URL로 쇼츠 후보 뽑기"에서 호출하는 워크플로우. 임의의 영상 URL 하나를 분석해 후보 10개를 만든다 (주 사용 흐름)
  - `daily-analyze.yml` — playlist에서 오늘자 영상을 자동으로 찾아 분석. 예약 실행은 꺼져 있고 수동(`program` 입력으로 하나만 실행 가능)으로만 쓴다 (아래 "YouTube가 봇 차단할 때" 참고)
  - `render-short.yml` — 로컬 웹페이지에서 호출하는 렌더링 워크플로우 (직접 Actions 탭에서 수동 실행도 가능)

#### YouTube가 "Sign in to confirm you're not a bot"으로 막을 때

GitHub Actions 같은 클라우드 서버 IP는 유튜브가 봇으로 의심해서 차단하는 경우가 흔하다.
코드에 기본으로 android/tv 클라이언트로 우회하는 처리가 들어있지만, 그래도 막히면
실제 로그인된 브라우저의 쿠키를 넘겨주는 방법으로 해결한다:

1. 크롬/엣지에 "Get cookies.txt LOCALLY" 같은 확장 프로그램을 설치
2. 유튜브에 로그인된 상태로 youtube.com 접속 → 확장 프로그램 아이콘 클릭 → 쿠키를 내보내기(Export)
3. 내려받은 `cookies.txt` 파일을 메모장으로 열어서 전체 내용을 복사
4. GitHub 저장소 → `Settings → Secrets and variables → Actions → New repository secret`
5. Name에 `YOUTUBE_COOKIES` 입력, Secret에 복사한 내용 전체를 붙여넣고 저장

> 이 쿠키는 내 유튜브 로그인 정보이므로, 반드시 GitHub Secrets 입력창에만 붙여넣는다.
> 저장소 파일이나 다른 곳에 커밋/붙여넣기 하면 안 된다. `YOUTUBE_COOKIES`를 등록하지
> 않아도 파이프라인은 동작을 시도하며, 이 secret은 어디까지나 추가 보험이다.

**쿠키는 며칠 지나면 다시 만료될 수 있다.** 특히 `daily-analyze.yml`처럼 하루에 영상
~20개씩(두 프로그램 합쳐 ~40개) 조회하는 경로는 세션이 금방 무효화되는 경향이 있었다.
그래서 예약 실행은 꺼두고 `analyze-url.yml`(영상 1개당 요청 1번)을 주 사용 흐름으로
바꿨다 — 요청량이 훨씬 적어서 같은 쿠키가 더 오래 간다. 그래도 언젠가 다시
"Sign in to confirm you're not a bot" 에러가 뜨면, 위 1~5단계로 쿠키를 새로 발급받아
`YOUTUBE_COOKIES`를 갱신하면 된다.

### 2. 로컬 리뷰 웹페이지 설정

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp webui/.env.example webui/.env
# webui/.env를 열어 GITHUB_TOKEN(레포에 대해 Actions 읽기/쓰기 권한이 있는 PAT)을 채운다

uvicorn webui.server:app --reload --port 8787
# http://localhost:8787 접속
```

`GITHUB_TOKEN`은 render-short.yml을 트리거하고 실행 결과(아티팩트)를 내려받는 데만
쓰이며, 저장소 밖으로 나가지 않는다. `webui/.env`는 `.gitignore`에 포함되어 커밋되지 않는다.

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
2줄 강조색 훅 문구, `thumbnail_text`를 줄바꿈으로 구분), 그 아래로 원본 영상을
화면 전체 너비에 꽉 차게 크롭해서 배치하고, 좌/우 상단에 방송사/코너 로고(현재는
텍스트 자리표시자, 실제 로고 이미지 파일이 생기면 이미지 오버레이로 교체 예정),
하단에는 실제 대사 타이밍에 맞춰 자동으로 바뀌는 자막을 합성한다. 위치/폰트/색상
등은 해당 파일 상단 상수에서 조정할 수 있다.

## 테스트

```bash
pip install -r requirements.txt pytest
pytest
```

유튜브 다운로드·Claude API 호출처럼 외부 네트워크가 필요한 부분은 유닛 테스트로
검증할 수 없어서, 정규식 매칭/자막 파싱/ffmpeg 필터 그래프 구성 같은 순수 로직만
테스트로 커버했다. 전체 파이프라인은 GitHub Actions 실행 결과로 확인한다.
