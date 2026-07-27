"""Minimal GitHub Actions REST client used to trigger and track the
render-short.yml workflow from the local review web UI."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

API_BASE = "https://api.github.com"


class ConfigError(RuntimeError):
    pass


@dataclass
class GithubConfig:
    token: str
    repo: str  # "owner/repo"
    ref: str

    @property
    def owner_repo(self) -> tuple[str, str]:
        owner, repo = self.repo.split("/", 1)
        return owner, repo


def load_config() -> GithubConfig:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    ref = os.environ.get("GITHUB_REF", "main")
    if not token or not repo:
        raise ConfigError(
            "GITHUB_TOKEN and GITHUB_REPO must be set (see webui/.env.example)"
        )
    return GithubConfig(token=token, repo=repo, ref=ref)


def _headers(cfg: GithubConfig) -> dict:
    return {
        "Authorization": f"Bearer {cfg.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def dispatch_workflow(cfg: GithubConfig, workflow_file: str, inputs: dict) -> None:
    owner, repo = cfg.owner_repo
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches"
    payload = {"ref": cfg.ref, "inputs": inputs}
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=_headers(cfg), json=payload, timeout=30)
        resp.raise_for_status()


async def dispatch_render(
    cfg: GithubConfig,
    program: str,
    video_id: str,
    start_sec: str,
    end_sec: str,
    thumbnail_text: str,
) -> None:
    await dispatch_workflow(
        cfg,
        "render-short.yml",
        {
            "program": program,
            "video_id": video_id,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "thumbnail_text": thumbnail_text,
        },
    )


async def dispatch_analyze_url(cfg: GithubConfig, url: str) -> None:
    await dispatch_workflow(cfg, "analyze-url.yml", {"url": url})


async def find_run_by_name(
    cfg: GithubConfig, workflow_file: str, run_name: str, since_iso: str
) -> dict | None:
    owner, repo = cfg.owner_repo
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/workflows/{workflow_file}/runs"
    params = {"event": "workflow_dispatch", "per_page": 20}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(cfg), params=params, timeout=30)
        resp.raise_for_status()
    for run in resp.json().get("workflow_runs", []):
        if run.get("name") == run_name and run.get("created_at", "") >= since_iso:
            return run
    return None


async def get_run(cfg: GithubConfig, run_id: int) -> dict:
    owner, repo = cfg.owner_repo
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/runs/{run_id}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(cfg), timeout=30)
        resp.raise_for_status()
    return resp.json()


async def list_artifacts(cfg: GithubConfig, run_id: int) -> list[dict]:
    owner, repo = cfg.owner_repo
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers(cfg), timeout=30)
        resp.raise_for_status()
    return resp.json().get("artifacts", [])


async def download_artifact_zip(cfg: GithubConfig, artifact_id: int) -> bytes:
    owner, repo = cfg.owner_repo
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip"
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, headers=_headers(cfg), timeout=120)
        resp.raise_for_status()
    return resp.content
