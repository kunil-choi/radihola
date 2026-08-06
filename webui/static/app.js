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
// render/remove buttons added later by "+ 새 구간 추가"
document.addEventListener("click", (e) => {
  if (e.target.matches(".remove-clip-btn")) {
    e.target.closest(".custom-clip").remove();
    return;
  }
  if (e.target.matches(".render-btn")) {
    handleRenderClick(e.target);
  }
});

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

  const form = new URLSearchParams({
    program: btn.dataset.program,
    video_id: btn.dataset.videoId,
    start_sec: String(startSec),
    end_sec: String(endSec),
    thumbnail_text: thumbInput.value,
    guest_label: guestLabelInput ? guestLabelInput.value : "",
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
      statusEl.innerHTML = `완료! <a href="${job.download_url}" download>다운로드</a>`;
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
