"""Local review web app for radihola.

Run with:  uvicorn webui.server:app --reload --port 8787

Shows the shorts candidates that the daily-analyze GitHub Action committed
into data/, lets you preview each one (via the YouTube embed, seeked to the
candidate's timestamp) and edit the thumbnail text, then triggers the
render-short.yml GitHub Action to produce the final vertical mp4 and serves
it back for download once the run finishes.
"""

from __future__ import annotations

import asyncio
import io
import json
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import github_actions

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DOWNLOADS_DIR = Path(__file__).resolve().parent / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="radihola")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app.mount("/downloads", StaticFiles(directory=str(DOWNLOADS_DIR)), name="downloads")
app.mount(
    "/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static"
)

RENDER_JOBS: dict[str, dict] = {}


def scan_candidate_groups() -> list[dict]:
    groups = []
    for path in sorted(DATA_DIR.glob("*/*/*/candidates.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        groups.append(data)
    return groups


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    groups = scan_candidate_groups()
    return templates.TemplateResponse(request, "index.html", {"groups": groups})


@app.post("/refresh")
def refresh():
    subprocess.run(["git", "pull", "--ff-only"], cwd=REPO_ROOT, check=False)
    return RedirectResponse("/", status_code=303)


ANALYZE_URL_JOBS: dict[str, dict] = {}


@app.post("/analyze-url")
async def start_analyze_url(url: str = Form(...)):
    job_id = uuid.uuid4().hex[:12]
    ANALYZE_URL_JOBS[job_id] = {"status": "starting", "message": ""}
    asyncio.create_task(_run_analyze_url_job(job_id, url))
    return {"job_id": job_id}


@app.get("/analyze-url-jobs/{job_id}")
def analyze_url_job_status(job_id: str):
    job = ANALYZE_URL_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


async def _run_analyze_url_job(job_id: str, url: str) -> None:
    job = ANALYZE_URL_JOBS[job_id]
    try:
        cfg = github_actions.load_config()
    except github_actions.ConfigError as e:
        job.update(status="error", message=str(e))
        return

    run_name = f"AnalyzeURL {url}"
    since_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        job.update(status="dispatching", message="워크플로우 실행 요청 중...")
        await github_actions.dispatch_analyze_url(cfg, url)

        job.update(status="queued", message="GitHub Actions에서 실행 대기 중...")
        run = None
        for _ in range(24):  # up to ~2 minutes
            await asyncio.sleep(5)
            run = await github_actions.find_run_by_name(cfg, "analyze-url.yml", run_name, since_iso)
            if run:
                break
        if run is None:
            job.update(status="error", message="워크플로우 실행을 찾지 못했습니다 (타임아웃)")
            return

        run_id = run["id"]
        job.update(
            status="running",
            message="영상 분석 중... (자막 다운로드 + 후보 생성, 몇 분 걸릴 수 있습니다)",
            run_url=run.get("html_url"),
        )
        while True:
            await asyncio.sleep(8)
            run = await github_actions.get_run(cfg, run_id)
            if run["status"] == "completed":
                break
            job.update(message=f"상태: {run['status']}")

        if run["conclusion"] != "success":
            job.update(
                status="error",
                message=f"워크플로우 실패 (conclusion={run['conclusion']})",
                run_url=run.get("html_url"),
            )
            return

        job.update(status="pulling", message="결과 반영 중 (git pull)...")
        subprocess.run(["git", "pull", "--ff-only"], cwd=REPO_ROOT, check=False)

        job.update(status="done", message="완료! 아래 목록에 후보가 추가됐습니다.")
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        job.update(status="error", message=str(e))


@app.post("/render")
async def start_render(
    program: str = Form(...),
    video_id: str = Form(...),
    start_sec: str = Form(...),
    end_sec: str = Form(...),
    thumbnail_text: str = Form(...),
):
    job_id = uuid.uuid4().hex[:12]
    RENDER_JOBS[job_id] = {"status": "starting", "message": ""}
    asyncio.create_task(
        _run_render_job(job_id, program, video_id, start_sec, end_sec, thumbnail_text)
    )
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = RENDER_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


async def _run_render_job(
    job_id: str, program: str, video_id: str, start_sec: str, end_sec: str, thumbnail_text: str
) -> None:
    job = RENDER_JOBS[job_id]
    try:
        cfg = github_actions.load_config()
    except github_actions.ConfigError as e:
        job.update(status="error", message=str(e))
        return

    run_name = f"Render {program} {video_id} {start_sec}-{end_sec}"
    since_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        job.update(status="dispatching", message="워크플로우 실행 요청 중...")
        await github_actions.dispatch_render(
            cfg, program, video_id, start_sec, end_sec, thumbnail_text
        )

        job.update(status="queued", message="GitHub Actions에서 실행 대기 중...")
        run = None
        for _ in range(24):  # up to ~2 minutes
            await asyncio.sleep(5)
            run = await github_actions.find_run_by_name(cfg, "render-short.yml", run_name, since_iso)
            if run:
                break
        if run is None:
            job.update(status="error", message="워크플로우 실행을 찾지 못했습니다 (타임아웃)")
            return

        run_id = run["id"]
        job.update(status="running", message="렌더링 중...", run_url=run.get("html_url"))
        while True:
            await asyncio.sleep(8)
            run = await github_actions.get_run(cfg, run_id)
            if run["status"] == "completed":
                break
            job.update(message=f"상태: {run['status']}")

        if run["conclusion"] != "success":
            job.update(
                status="error",
                message=f"워크플로우 실패 (conclusion={run['conclusion']})",
                run_url=run.get("html_url"),
            )
            return

        job.update(status="downloading", message="결과 파일 다운로드 중...")
        artifacts = await github_actions.list_artifacts(cfg, run_id)
        if not artifacts:
            job.update(status="error", message="아티팩트를 찾지 못했습니다")
            return

        zip_bytes = await github_actions.download_artifact_zip(cfg, artifacts[0]["id"])
        job_dir = DOWNLOADS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(job_dir)

        mp4_files = list(job_dir.glob("*.mp4"))
        if not mp4_files:
            job.update(status="error", message="다운로드한 아티팩트에 mp4가 없습니다")
            return

        job.update(
            status="done",
            message="완료",
            download_url=f"/downloads/{job_id}/{mp4_files[0].name}",
        )
    except Exception as e:  # noqa: BLE001 - surface any failure to the UI
        job.update(status="error", message=str(e))
