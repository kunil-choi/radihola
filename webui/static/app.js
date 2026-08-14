const analyzeUrlForm = document.getElementById("analyze-url-form");
if (analyzeUrlForm) {
  analyzeUrlForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("analyze-url-input");
    const statusEl = document.getElementById("analyze-url-status");
    const btn = analyzeUrlForm.querySelector("button");

    btn.disabled = true;
    statusEl.textContent = "요청 중...";

    const form = new URLSearchParams({ url: input.value });

    let jobId;
    try {
      const res = await fetch("/analyze-url", { method: "POST", body: form });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      ({ job_id: jobId } = await res.json());
    } catch (err) {
      statusEl.textContent = `요청 실패: ${err}`;
      btn.disabled = false;
      return;
    }

    const poll = async () => {
      let job;
      try {
        const res = await fetch(`/analyze-url-jobs/${jobId}`);
        job = await res.json();
      } catch (err) {
        statusEl.textContent = `상태 확인 실패: ${err}`;
        btn.disabled = false;
        return;
      }

      if (job.status === "done") {
        statusEl.textContent = `${job.message} 새로고침합니다...`;
        setTimeout(() => window.location.reload(), 1500);
        return;
      }
      if (job.status === "error") {
        statusEl.textContent = `오류: ${job.message}`;
        btn.disabled = false;
        return;
      }

      const runLink = job.run_url ? ` (<a href="${job.run_url}" target="_blank">실행 로그</a>)` : "";
      statusEl.innerHTML = `${job.status}: ${job.message || ""}${runLink}`;
      setTimeout(poll, 3000);
    };
    poll();
  });
}

// "mm:ss", "h:mm:ss", or plain seconds -> seconds. Throws on anything else.
function parseTimeToSeconds(raw) {
  const text = (raw || "").trim();
  if (!text) throw new Error("시간을 입력하세요");
  const parts = text.split(":");
  if (parts.length > 3 || parts.some((p) => p.trim() === "" || Number.isNaN(Number(p)))) {
    throw new Error(`"${raw}" 형식을 이해할 수 없습니다 (mm:ss 또는 h:mm:ss)`);
  }
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

// "+ 새 구간 추가": clone this group's row template into its list, so you
// can stack up several custom in/out clips before rendering any of them
document.querySelectorAll(".add-custom-clip-btn").forEach((addBtn) => {
  addBtn.addEventListener("click", () => {
    const section = addBtn.closest(".custom-clips");
    const template = section.querySelector(".custom-clip-template");
    const list = section.querySelector(".custom-clip-list");
    list.appendChild(template.content.cloneNode(true));
  });
});

// delegated (not bound per-button at load time) so it also covers
// render/remove/caption buttons added later by "+ 새 구간 추가"
document.addEventListener("click", (e) => {
  if (e.target.matches(".remove-clip-btn")) {
    e.target.closest(".custom-clip").remove();
    return;
  }
  if (e.target.matches(".render-btn")) {
    handleRenderClick(e.target);
    return;
  }
  if (e.target.matches(".remove-caption-btn")) {
    e.target.closest(".caption-row").remove();
    return;
  }
  if (e.target.matches(".load-captions-btn")) {
    handleLoadCaptionsClick(e.target);
  }
});

function captionRowHtml(cap) {
  const row = document.createElement("div");
  row.className = "caption-row";
  row.dataset.start = cap.start_sec;
  row.dataset.end = cap.end_sec;

  const time = document.createElement("span");
  time.className = "caption-time";
  time.textContent = formatHms(cap.start_sec);
  row.appendChild(time);

  const textarea = document.createElement("textarea");
  textarea.className = "caption-text";
  textarea.rows = 1;
  textarea.value = cap.text;
  row.appendChild(textarea);

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "remove-caption-btn";
  removeBtn.title = "이 자막 줄 삭제";
  removeBtn.textContent = "✕";
  row.appendChild(removeBtn);

  return row;
}

function formatHms(sec) {
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const mm = String(m).padStart(h ? 2 : 1, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
}

async function handleLoadCaptionsClick(btn) {
  const card = btn.closest(".candidate");
  const editor = btn.closest(".captions-editor");
  const rowsContainer = editor.querySelector(".caption-rows");
  const startInput = card.querySelector(".clip-start");
  const endInput = card.querySelector(".clip-end");

  let startSec, endSec;
  try {
    startSec = parseTimeToSeconds(startInput.value);
    endSec = parseTimeToSeconds(endInput.value);
  } catch (err) {
    rowsContainer.textContent = err.message;
    return;
  }
  if (endSec <= startSec) {
    rowsContainer.textContent = "끝 시각은 시작 시각보다 뒤여야 합니다.";
    return;
  }

  const renderBtn = card.querySelector(".render-btn");
  const program = renderBtn.dataset.program;
  const videoId = renderBtn.dataset.videoId;

  btn.disabled = true;
  rowsContainer.textContent = "불러오는 중...";
  try {
    const params = new URLSearchParams({
      program,
      video_id: videoId,
      start_sec: String(startSec),
      end_sec: String(endSec),
    });
    const res = await fetch(`/captions?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const { captions } = await res.json();

    rowsContainer.innerHTML = "";
    if (captions.length === 0) {
      rowsContainer.textContent = "이 구간에는 자막이 없습니다.";
    } else {
      captions.forEach((cap) => rowsContainer.appendChild(captionRowHtml(cap)));
    }
    editor.dataset.loaded = "true";
  } catch (err) {
    rowsContainer.textContent = `자막 불러오기 실패: ${err}`;
  } finally {
    btn.disabled = false;
  }
}

async function handleRenderClick(btn) {
  const card = btn.closest(".candidate");
  const statusEl = card.querySelector(".job-status");
  const thumbInput = card.querySelector(".thumb-text");

  // candidate cards carry start/end as data attributes; custom-clip cards
  // (no data-start/data-end) carry them as user-editable time inputs instead
  let startSec = btn.dataset.start;
  let endSec = btn.dataset.end;
  const startInput = card.querySelector(".clip-start");
  const endInput = card.querySelector(".clip-end");
  if (startInput && endInput) {
    try {
      startSec = parseTimeToSeconds(startInput.value);
      endSec = parseTimeToSeconds(endInput.value);
    } catch (err) {
      statusEl.textContent = err.message;
      return;
    }
    if (endSec <= startSec) {
      statusEl.textContent = "끝 시각은 시작 시각보다 뒤여야 합니다.";
      return;
    }
  }

  btn.disabled = true;
  statusEl.textContent = "요청 중...";

  const guestLabelInput = btn.closest(".group")?.querySelector(".guest-label-input");

  // only send captions once the editor has actual rows to send - candidate
  // cards render them up front, custom clips only after "자막 불러오기"; if
  // never loaded, leave the field blank so the backend falls back to its own
  // stored/derived captions instead of wiping them out
  const captionsEditor = card.querySelector(".captions-editor");
  let captionsPayload = "";
  if (captionsEditor && captionsEditor.dataset.loaded === "true") {
    const rows = [...captionsEditor.querySelectorAll(".caption-row")];
    captionsPayload = JSON.stringify(
      rows.map((row) => ({
        start_sec: parseFloat(row.dataset.start),
        end_sec: parseFloat(row.dataset.end),
        text: row.querySelector(".caption-text").value,
      }))
    );
  }

  const form = new URLSearchParams({
    program: btn.dataset.program,
    video_id: btn.dataset.videoId,
    start_sec: String(startSec),
    end_sec: String(endSec),
    thumbnail_text: thumbInput.value,
    guest_label: guestLabelInput ? guestLabelInput.value : "",
    captions: captionsPayload,
  });

  let jobId;
  try {
    const res = await fetch("/render", { method: "POST", body: form });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    ({ job_id: jobId } = await res.json());
  } catch (err) {
    statusEl.textContent = `요청 실패: ${err}`;
    btn.disabled = false;
    return;
  }

  const poll = async () => {
    let job;
    try {
      const res = await fetch(`/jobs/${jobId}`);
      job = await res.json();
    } catch (err) {
      statusEl.textContent = `상태 확인 실패: ${err}`;
      btn.disabled = false;
      return;
    }

    if (job.status === "done") {
      const savedNote = job.saved_path
        ? `저장됨: <code>${job.saved_path}</code>`
        : "Dropbox 폴더 저장 실패 - 아래 링크로 다운로드하세요";
      statusEl.innerHTML = `완료! ${savedNote} (<a href="${job.download_url}" download>다운로드</a>)`;
      btn.disabled = false;
      return;
    }
    if (job.status === "error") {
      statusEl.textContent = `오류: ${job.message}`;
      btn.disabled = false;
      return;
    }

    const runLink = job.run_url ? ` (<a href="${job.run_url}" target="_blank">실행 로그</a>)` : "";
    statusEl.innerHTML = `${job.status}: ${job.message || ""}${runLink}`;
    setTimeout(poll, 3000);
  };
  poll();
}
