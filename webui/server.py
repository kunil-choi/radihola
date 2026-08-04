"""Local review web app for radihola.

Run with:  uvicorn webui.server:app --reload --port 8787

Shows the shorts candidates committed into data/, lets you preview each one
(via the YouTube embed, seeked to the candidate's timestamp) and edit the
thumbnail text. Both "후보 뽑기" (analyze-url) and "쇼츠 만들기" (render) run
the radihola pipeline directly on this machine (not via GitHub Actions) so
that YouTube sees your own network's IP instead of a cloud runner's - cloud
IPs are frequently bot-blocked by YouTube regardless of cookies. Results are
committed and pushed with your local git credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv(Path(__file__).resolve().parent / ".env")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from radihola import cli as radihola_cli  # noqa: E402

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

MAX_CANDIDATE_AGE_DAYS = 4


def _git_commit_and_push(commit_message: str, attempts: int = 5) -> None:
    subprocess.run(["git", "add", "-A", "data/"], cwd=REPO_ROOT, check=True)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT
    )
    if diff.returncode == 0:
        return  # nothing to commit
    subprocess.run(["git", "commit", "-m", commit_message], cwd=REPO_ROOT, check=True)
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    for attempt in range(1, attempts + 1):
        result = subprocess.run(["git", "push", "origin", f"HEAD:{branch}"], cwd=REPO_ROOT)
        if result.returncode == 0:
            return
        if attempt == attempts:
            raise subprocess.CalledProcessError(result.returncode, result.args)
        # someone else (another machine, a merged PR, the cleanup job) pushed
        # in the meantime - rebase our new commit on top and retry
        subprocess.run(["git", "fetch", "origin", branch], cwd=REPO_ROOT, check=True)
        subprocess.run(["git", "rebase", f"origin/{branch}"], cwd=REPO_ROOT, check=True)


def _cleanup_old_groups() -> bool:
    """Delete candidate groups older than MAX_CANDIDATE_AGE_DAYS. Returns True if anything was removed."""
    today = date.today()
    removed = False
    for path in DATA_DIR.glob("*/*/*/candidates.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            group_date = date.fromisoformat(data["date"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            continue
        if (today - group_date).days > MAX_CANDIDATE_AGE_DAYS:
            shutil.rmtree(path.parent, ignore_errors=True)
            removed = True
    return removed


def scan_candidate_groups() -> list[dict]:
    groups = []
    for path in sorted(
        DATA_DIR.glob("*/*/*/candidates.json"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        groups.append(data)
    return groups


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if _cleanup_old_groups():
        try:
            _git_commit_and_push(f"data: remove candidates older than {MAX_CANDIDATE_AGE_DAYS} days")
        except subprocess.CalledProcessError as e:
            print(f"[cleanup] failed to commit/push deletions: {e}", file=sys.stderr)
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
        job.update(
            status="running",
            message="영상 분석 중... (자막 다운로드 + 후보 생성, 몇 분 걸릴 수 있습니다)",
        )
        loop = asyncio.get_event_loop()
        ns = argparse.Namespace(url=url)
        await loop.run_in_executor(None, radihola_cli.cmd_analyze_url, ns)

        job.update(status="pushing", message="결과 커밋/푸시 중...")
        await loop.run_in_executor(
            None, _git_commit_and_push, f"data: shorts candidates for {url} ({date.today().isoformat()})"
        )

        job.update(status="done", message="완료! 아래 목록에 후보가 추가됐습니다.")
    except (Exception, SystemExit) as e:  # noqa: BLE001 - surface any failure to the UI
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
        job.update(status="running", message="렌더링 중...")

        job_dir = DOWNLOADS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        clip_start = float(start_sec)
        clip_end = float(end_sec)
        out_path = job_dir / f"{video_id}_{clip_start:g}-{clip_end:g}.mp4"

        ns = argparse.Namespace(
            program=program,
            video_id=video_id,
            start=float(start_sec),
            end=float(end_sec),
            thumbnail_text=thumbnail_text,
            candidate_file=None,
            candidate_id=1,
            out=str(out_path),
        )
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, radihola_cli.cmd_render, ns)

        if not out_path.exists():
            job.update(status="error", message="렌더링 결과 파일을 찾지 못했습니다")
            return

        job.update(
            status="done",
            message="완료",
            download_url=f"/downloads/{job_id}/{out_path.name}",
        )
    except (Exception, SystemExit) as e:  # noqa: BLE001 - surface any failure to the UI
        job.update(status="error", message=str(e))
