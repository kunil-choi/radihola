document.querySelectorAll(".render-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const card = btn.closest(".candidate");
    const statusEl = card.querySelector(".job-status");
    const thumbInput = card.querySelector(".thumb-text");

    btn.disabled = true;
    statusEl.textContent = "요청 중...";

    const form = new URLSearchParams({
      program: btn.dataset.program,
      video_id: btn.dataset.videoId,
      start_sec: btn.dataset.start,
      end_sec: btn.dataset.end,
      thumbnail_text: thumbInput.value,
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
  });
});
