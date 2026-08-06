# 폰트

렌더링된 쇼츠의 상단 제목 배너와 하단 자막에 쓰이는 표시용(display) 폰트.

- `BlackHanSans-Regular.ttf` — [Black Han Sans](https://fonts.google.com/specimen/Black+Han+Sans)
  (Google Fonts, SIL Open Font License 1.1 — `OFL.txt` 참고, 무료 상업적 이용 가능).
  두껍고 각진 방송 자막 스타일이라 예능/시사 쇼츠 자막에 흔히 쓰이는 서체다.

로고 이미지(`assets/logos/`)와 마찬가지로 실제 파일이 없으면 `src/radihola/render.py`가
`DEFAULT_FONT`(NanumGothicBold)로 대체한다. 다른 폰트로 바꾸고 싶으면 이 파일을 같은
이름으로 교체하거나, `RADIHOLA_DISPLAY_FONT` 환경변수로 다른 경로를 지정하면 된다.
