/* Static-site (GitHub Pages) version of app.js.
 *
 * There is no backend here, so instead of POSTing to a local FastAPI server
 * (see app.js), this calls the GitHub REST API directly from the browser
 * using a token the user pastes in once (stored in localStorage only).
 */

const TOKEN_KEY = "radihola_gh_token";
const OWNER = "kunil-choi";
const REPO = "radihola";
const API = "https://api.github.com";

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}
function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t);
}

function ghHeaders() {
  return {
    Authorization: `Bearer ${getToken()}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function dispatchWorkflow(workflowFile, inputs) {
  const res = await fetch(
    `${API}/repos/${OWNER}/${REPO}/actions/workflows/${workflowFile}/dispatches`,
    {
      method: "POST",
      headers: { ...ghHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main", inputs }),
    }
  );
  if (!res.ok) {
    throw new Error(`디스패치 실패 (HTTP ${res.status}). 토큰과 권한을 확인하세요.`);
  }
}

async function findRunByName(workflowFile, runName, sinceIso) {
  const res = await fetch(
    `${API}/repos/${OWNER}/${REPO}/actions/workflows/${workflowFile}/runs?event=workflow_dispatch&per_page=20`,
    { headers: ghHeaders() }
  );
  if (!res.ok) throw new Error(`실행 목록 조회 실패 (HTTP ${res.status})`);
  const data = await res.json();
  return (
    (data.workflow_runs || []).find(
      (r) => r.name === runName && r.created_at >= sinceIso
    ) || null
  );
}

async function getRun(runId) {
  const res = await fetch(`${API}/repos/${OWNER}/${REPO}/actions/runs/${runId}`, {
    headers: ghHeaders(),
  });
  if (!res.ok) throw new Error(`실행 상태 조회 실패 (HTTP ${res.status})`);
  return res.json();
}

async function runWorkflowAndTrack(workflowFile, runName, inputs, onUpdate) {
  if (!getToken()) {
    onUpdate("error", "먼저 위쪽 'GitHub 토큰 설정'에서 토큰을 저장해주세요.");
    return;
  }
  const sinceIso = new Date().toISOString();
  try {
    onUpdate("dispatching", "워크플로우 실행 요청 중...");
    await dispatchWorkflow(workflowFile, inputs);

    onUpdate("queued", "GitHub Actions에서 실행 대기 중...");
    let run = null;
    for (let i = 0; i < 24; i++) {
      // up to ~2 minutes
      await sleep(5000);
      run = await findRunByName(workflowFile, runName, sinceIso);
      if (run) break;
    }
    if (!run) {
      onUpdate("error", "워크플로우 실행을 찾지 못했습니다 (타임아웃)");
      return;
    }

    onUpdate("running", "실행 중...", run.html_url);
    while (true) {
      await sleep(8000);
      run = await getRun(run.id);
      if (run.status === "completed") break;
      onUpdate("running", `상태: ${run.status}`, run.html_url);
    }

    if (run.conclusion !== "success") {
      onUpdate("error", `워크플로우 실패 (conclusion=${run.conclusion})`, run.html_url);
      return;
    }
    onUpdate(
      "done",
      "완료! 아래 실행 링크를 열어 하단 Artifacts에서 mp4를 다운로드하세요.",
      run.html_url
    );
  } catch (err) {
    onUpdate("error", String((err && err.message) || err));
  }
}

function renderStatus(el, status, message, runUrl) {
  const runLink = runUrl ? ` (<a href="${runUrl}" target="_blank">실행 링크</a>)` : "";
  el.innerHTML = `${status}: ${message || ""}${runLink}`;
}

// --- token bar ---
const tokenForm = document.getElementById("token-form");
const tokenInput = document.getElementById("token-input");
const tokenStatus = document.getElementById("token-status");

function refreshTokenStatus() {
  if (tokenStatus) tokenStatus.textContent = getToken() ? "(저장됨)" : "(미설정)";
}
refreshTokenStatus();

if (tokenForm) {
  tokenForm.addEventListener("submit", (e) => {
    e.preventDefault();
    setToken(tokenInput.value.trim());
    tokenInput.value = "";
    refreshTokenStatus();
  });
}

// --- reload button ---
const reloadBtn = document.getElementById("reload-btn");
if (reloadBtn) {
  reloadBtn.addEventListener("click", () => window.location.reload());
}

// --- analyze-url form ---
const analyzeUrlForm = document.getElementById("analyze-url-form");
if (analyzeUrlForm) {
  analyzeUrlForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("analyze-url-input");
    const statusEl = document.getElementById("analyze-url-status");
    const btn = analyzeUrlForm.querySelector("button");
    const url = input.value;

    btn.disabled = true;
    await runWorkflowAndTrack(
      "analyze-url.yml",
      `AnalyzeURL ${url}`,
      { url },
      (status, message, runUrl) => renderStatus(statusEl, status, message, runUrl)
    );
    btn.disabled = false;
  });
}

// --- "mm:ss"/"h:mm:ss"/plain-seconds -> seconds. Throws on anything else. ---
function parseTimeToSeconds(raw) {
  const text = (raw || "").trim();
  if (!text) throw new Error("시간을 입력하세요");
  const parts = text.split(":");
  if (parts.length > 3 || parts.some((p) => p.trim() === "" || Number.isNaN(Number(p)))) {
    throw new Error(`"${raw}" 형식을 이해할 수 없습니다 (mm:ss 또는 h:mm:ss)`);
  }
  return parts.reduce((acc, p) => acc * 60 + Number(p), 0);
}

// --- "+ 새 구간 추가": clone this group's row template into its list ---
document.querySelectorAll(".add-custom-clip-btn").forEach((addBtn) => {
  addBtn.addEventListener("click", () => {
    const section = addBtn.closest(".custom-clips");
    const template = section.querySelector(".custom-clip-template");
    const list = section.querySelector(".custom-clip-list");
    list.appendChild(template.content.cloneNode(true));
  });
});

// --- render buttons (delegated so it also covers buttons added later by
// "+ 새 구간 추가", not just the ones present at page load) ---
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
  const runName = `Render ${btn.dataset.program} ${btn.dataset.videoId} ${startSec}-${endSec}`;
  await runWorkflowAndTrack(
    "render-short.yml",
    runName,
    {
      program: btn.dataset.program,
      video_id: btn.dataset.videoId,
      start_sec: String(startSec),
      end_sec: String(endSec),
      thumbnail_text: thumbInput.value,
    },
    (status, message, runUrl) => renderStatus(statusEl, status, message, runUrl)
  );
  btn.disabled = false;
}
