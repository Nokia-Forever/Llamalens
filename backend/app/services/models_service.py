from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import DownloadJob, ModelFile
from app.schemas import AppSettings, DownloadCreate


EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="llamalens-download")
_cancelled_downloads: set[str] = set()
_cancel_lock = threading.Lock()


QUANT_RE = re.compile(
    r"(?:^|[-_.])(IQ\d(?:_[A-Z0-9]+)?|Q\d(?:_[A-Z0-9]+)+|F16|F32|BF16)(?:[-_.]|$)", re.IGNORECASE
)


def _is_within(path: Path, roots: list[str]) -> bool:
    resolved = path.resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve(strict=False))
            return True
        except ValueError:
            continue
    return False


def infer_quantization(name: str) -> str | None:
    match = QUANT_RE.search(name)
    return match.group(1).upper() if match else None


def scan_models(db: Session, roots: list[str]) -> dict[str, int]:
    discovered: dict[str, Path] = {}
    for root_text in roots:
        root = Path(root_text).expanduser()
        if not root.exists() or not root.is_dir():
            continue
        for path in root.rglob("*.gguf"):
            if path.is_file():
                discovered[str(path.resolve())] = path

    existing = {row.path: row for row in db.scalars(select(ModelFile)).all()}
    for path_text, path in discovered.items():
        stat = path.stat()
        row = existing.get(path_text)
        if row is None:
            row = ModelFile(path=path_text, name=path.name)
            db.add(row)
        row.name = path.name
        row.size_bytes = stat.st_size
        row.quantization = infer_quantization(path.name)
        row.modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        row.available = True
        row.scanned_at = datetime.now(timezone.utc)
    for path_text, row in existing.items():
        if path_text not in discovered:
            row.available = False
    db.commit()
    return {"found": len(discovered), "unavailable": sum(1 for row in existing.values() if not row.available)}


def search_huggingface(query: str, limit: int = 20) -> list[dict[str, object]]:
    response = httpx.get(
        "https://huggingface.co/api/models",
        params={"search": query, "limit": max(1, min(limit, 50)), "full": "true"},
        timeout=20,
        follow_redirects=True,
    )
    response.raise_for_status()
    results: list[dict[str, object]] = []
    for model in response.json():
        model_id = model.get("id") or model.get("modelId")
        siblings = model.get("siblings") or []
        ggufs = [item.get("rfilename") for item in siblings if str(item.get("rfilename", "")).lower().endswith(".gguf")]
        if not model_id or not ggufs:
            continue
        results.append(
            {
                "model_id": model_id,
                "downloads": model.get("downloads", 0),
                "likes": model.get("likes", 0),
                "files": [
                    {
                        "name": Path(filename).name,
                        "remote_path": filename,
                        "url": f"https://huggingface.co/{model_id}/resolve/main/{filename}",
                    }
                    for filename in ggufs
                ],
            }
        )
    return results


def create_download(db: Session, settings: AppSettings, request: DownloadCreate) -> DownloadJob:
    root = Path(request.target_root).expanduser().resolve(strict=False)
    if str(root) not in [str(Path(item).expanduser().resolve(strict=False)) for item in settings.model_roots]:
        raise ValueError("下载目标必须是设置中登记的模型目录")
    if Path(request.filename).name != request.filename or request.filename in {".", ".."}:
        raise ValueError("filename 只能是文件名，不能包含目录")
    target = (root / request.filename).resolve(strict=False)
    if not _is_within(target, settings.model_roots):
        raise ValueError("下载路径超出模型目录")
    if target.exists() or target.with_suffix(target.suffix + ".part").exists():
        raise ValueError("目标文件已存在")
    job = DownloadJob(id=str(uuid.uuid4()), url=request.url, target_path=str(target), status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    EXECUTOR.submit(_run_download, job.id, settings.download_timeout_seconds)
    return job


def cancel_download(job_id: str) -> None:
    with _cancel_lock:
        _cancelled_downloads.add(job_id)


def _run_download(job_id: str, timeout_seconds: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()
        target = Path(job.target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        with httpx.stream("GET", job.url, timeout=timeout_seconds, follow_redirects=True) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            job.total_bytes = int(content_length) if content_length and content_length.isdigit() else None
            db.commit()
            written = 0
            cancelled = False
            with part.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    with _cancel_lock:
                        if job_id in _cancelled_downloads:
                            job.status = "cancelled"
                            job.finished_at = datetime.now(timezone.utc)
                            db.commit()
                            cancelled = True
                            break
                    handle.write(chunk)
                    written += len(chunk)
                    job.downloaded_bytes = written
                    db.commit()
            if cancelled:
                part.unlink(missing_ok=True)
                return
        part.replace(target)
        job.status = "succeeded"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # background job must persist diagnostics
        job = db.get(DownloadJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        with _cancel_lock:
            _cancelled_downloads.discard(job_id)
        db.close()
