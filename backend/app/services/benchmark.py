from __future__ import annotations

import json
import math
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BenchmarkAttempt, BenchmarkJob, Profile, ProfileVersion, SwitchJob
from app.schemas import AppSettings, BenchmarkCreate
from app.services.job_control import EXECUTION_LOCK
from app.services.settings_service import get_settings


BENCHMARK_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llamalens-benchmark")
_cancelled_jobs: set[str] = set()
_cancel_lock = threading.Lock()


def create_benchmark_job(db: Session, payload: BenchmarkCreate) -> BenchmarkJob:
    switching = db.scalar(select(SwitchJob).where(SwitchJob.status.in_(["queued", "activating"])).limit(1))
    if switching is not None:
        raise ValueError("Profile 正在切换，完成后才能创建 Benchmark")
    active = db.scalar(select(Profile).where(Profile.is_active.is_(True)))
    if payload.profile_id and (active is None or payload.profile_id != active.id):
        raise ValueError("Benchmark 只能关联当前激活的 Profile")

    profile_id = active.id if active is not None else None
    config_payload = payload.model_dump(mode="json")
    if active is not None:
        version = db.scalar(
            select(ProfileVersion)
            .where(ProfileVersion.profile_id == active.id)
            .order_by(ProfileVersion.created_at.desc())
            .limit(1)
        )
        config_payload["profile_snapshot"] = {
            "id": active.id,
            "name": active.name,
            "model_path": active.model_path,
            "profile_version_id": version.id if version else None,
            "argv": json.loads(version.argv_json) if version else None,
        }
    else:
        config_payload["profile_snapshot"] = None

    job = BenchmarkJob(
        id=str(uuid.uuid4()),
        name=payload.name,
        profile_id=profile_id,
        status="queued",
        config_json=json.dumps(config_payload, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    BENCHMARK_EXECUTOR.submit(_run_job, job.id)
    return job


def cancel_benchmark(job_id: str) -> None:
    with _cancel_lock:
        _cancelled_jobs.add(job_id)


def _is_cancelled(job_id: str) -> bool:
    with _cancel_lock:
        return job_id in _cancelled_jobs


def _base_payload(config: BenchmarkCreate, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = dict(config.extra_params)
    payload.update({
        "prompt": config.prompt,
        "n_predict": config.max_tokens,
        "temperature": config.temperature,
        "cache_prompt": config.cache_prompt,
        "stream": stream,
    })
    if config.seed is not None:
        payload["seed"] = config.seed
    if config.stop:
        payload["stop"] = config.stop
    payload["stream"] = stream
    return payload


def _find_timings(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        timings = payload.get("timings")
        if isinstance(timings, dict):
            return timings
        for value in payload.values():
            found = _find_timings(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_timings(value)
            if found:
                return found
    return None


def _content_from_event(event: dict[str, Any]) -> str:
    content = event.get("content")
    if isinstance(content, str):
        return content
    choices = event.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        text = choice.get("text")
        if isinstance(text, str):
            return text
        delta = choice.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            return delta["content"]
    return ""


def _parse_number(mapping: dict[str, Any] | None, *keys: str) -> float | None:
    if not mapping:
        return None
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _gpu_snapshot() -> dict[str, Any]:
    argv = [
        "nvidia-smi",
        "--query-gpu=index,memory.used,memory.total,utilization.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=3, check=False)
        if completed.returncode != 0:
            return {}
        gpus = []
        for line in completed.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 5:
                gpus.append(
                    {
                        "index": int(parts[0]),
                        "memory_used_mb": float(parts[1]),
                        "memory_total_mb": float(parts[2]),
                        "utilization_percent": float(parts[3]),
                        "power_watts": float(parts[4]),
                    }
                )
        return {"nvidia": gpus}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


class _ResourceSampler:
    def __init__(self, interval_seconds: float = 0.5) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="llamalens-resource-sampler", daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            snapshot = _gpu_snapshot()
            if snapshot:
                self.samples.append(snapshot)
            self._stop.wait(self.interval_seconds)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def summary(self) -> dict[str, Any]:
        per_gpu: dict[int, dict[str, list[float]]] = {}
        for sample in self.samples:
            for gpu in sample.get("nvidia", []):
                index = int(gpu["index"])
                bucket = per_gpu.setdefault(index, {"memory_used_mb": [], "utilization_percent": [], "power_watts": []})
                for key in bucket:
                    value = gpu.get(key)
                    if isinstance(value, (int, float)):
                        bucket[key].append(float(value))
        return {
            "sample_count": len(self.samples),
            "nvidia": [
                {
                    "index": index,
                    **{f"{key}_max": max(values) if values else None for key, values in metrics.items()},
                    **{f"{key}_mean": statistics.fmean(values) if values else None for key, values in metrics.items()},
                }
                for index, metrics in sorted(per_gpu.items())
            ],
        }


def _stream_measurement(settings: AppSettings, config: BenchmarkCreate) -> dict[str, Any]:
    url = f"http://{settings.llama_host}:{settings.llama_port}{settings.request_path}"
    request_payload = _base_payload(config, stream=True)
    started = time.perf_counter()
    first_content: float | None = None
    last_content: float | None = None
    chunks: list[dict[str, Any]] = []
    output_text: list[str] = []
    timings: dict[str, Any] | None = None
    with _ResourceSampler() as sampler:
        with httpx.Client(timeout=config.timeout_seconds) as client:
            with client.stream("POST", url, json=request_payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    data = line[5:].strip() if line.startswith("data:") else line.strip()
                    if data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    chunks.append(event)
                    content = _content_from_event(event)
                    if content:
                        now = time.perf_counter()
                        if first_content is None:
                            first_content = now
                        last_content = now
                        output_text.append(content)
                    event_timings = _find_timings(event)
                    if event_timings:
                        timings = event_timings
    finished = time.perf_counter()
    predicted_n = _parse_number(timings, "predicted_n", "tokens_predicted")
    client_decode = None
    if first_content is not None and last_content is not None and predicted_n and predicted_n > 1 and last_content > first_content:
        client_decode = (predicted_n - 1) / (last_content - first_content)
    return {
        "request": request_payload,
        "raw": {"events": chunks, "content": "".join(output_text)},
        "timings": timings,
        "ttft_ms": (first_content - started) * 1000 if first_content is not None else None,
        "total_ms": (finished - started) * 1000,
        "client_decode_tps": client_decode,
        "resource": sampler.summary(),
    }


def _non_stream_timings(settings: AppSettings, config: BenchmarkCreate) -> dict[str, Any]:
    url = f"http://{settings.llama_host}:{settings.llama_port}{settings.request_path}"
    request_payload = _base_payload(config, stream=False)
    started = time.perf_counter()
    response = httpx.post(url, json=request_payload, timeout=config.timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    return {
        "request": request_payload,
        "raw": payload,
        "timings": _find_timings(payload),
        "total_ms": (time.perf_counter() - started) * 1000,
    }


def _measure(settings: AppSettings, config: BenchmarkCreate) -> dict[str, Any]:
    streamed = _stream_measurement(settings, config)
    measurement_mode = "stream"
    if streamed["timings"] is None:
        paired = _non_stream_timings(settings, config)
        streamed["paired"] = paired
        streamed["timings"] = paired["timings"]
        measurement_mode = "paired"
    timings = streamed["timings"]
    streamed.update(
        {
            "measurement_mode": measurement_mode,
            "prefill_tps": _parse_number(timings, "prompt_per_second", "prompt_per_second_value"),
            "decode_tps": _parse_number(timings, "predicted_per_second", "tokens_per_second"),
            "prompt_tokens": int(value) if (value := _parse_number(timings, "prompt_n", "tokens_evaluated")) is not None else None,
            "predicted_tokens": int(value) if (value := _parse_number(timings, "predicted_n", "tokens_predicted")) is not None else None,
        }
    )
    return streamed


def _persist_attempt(job_id: str, ordinal: int, warmup: bool, result: dict[str, Any] | None, error: Exception | None) -> None:
    db = SessionLocal()
    try:
        attempt = BenchmarkAttempt(
            job_id=job_id,
            ordinal=ordinal,
            warmup=warmup,
            status="failed" if error else "succeeded",
            request_json=json.dumps((result or {}).get("request", {}), ensure_ascii=False),
            raw_response_json=json.dumps((result or {}).get("raw", {}), ensure_ascii=False),
            measurement_mode=(result or {}).get("measurement_mode", "stream"),
            ttft_ms=(result or {}).get("ttft_ms"),
            prefill_tps=(result or {}).get("prefill_tps"),
            decode_tps=(result or {}).get("decode_tps"),
            client_decode_tps=(result or {}).get("client_decode_tps"),
            total_ms=(result or {}).get("total_ms"),
            prompt_tokens=(result or {}).get("prompt_tokens"),
            predicted_tokens=(result or {}).get("predicted_tokens"),
            resource_json=json.dumps((result or {}).get("resource", {}), ensure_ascii=False),
            error=f"{type(error).__name__}: {error}" if error else None,
        )
        if result and "paired" in result:
            attempt.raw_response_json = json.dumps(
                {"stream": result.get("raw", {}), "paired": result["paired"].get("raw", {})}, ensure_ascii=False
            )
        db.add(attempt)
        db.commit()
    finally:
        db.close()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _summarize(job_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        job = db.get(BenchmarkJob, job_id)
        attempts = [attempt for attempt in job.attempts if not attempt.warmup and attempt.status == "succeeded"] if job else []
        metrics = {
            "ttft_ms": [a.ttft_ms for a in attempts if a.ttft_ms is not None],
            "prefill_tps": [a.prefill_tps for a in attempts if a.prefill_tps is not None],
            "decode_tps": [a.decode_tps for a in attempts if a.decode_tps is not None],
            "client_decode_tps": [a.client_decode_tps for a in attempts if a.client_decode_tps is not None],
            "total_ms": [a.total_ms for a in attempts if a.total_ms is not None],
        }
        summary: dict[str, Any] = {
            "successes": len(attempts),
            "failures": len([a for a in (job.attempts if job else []) if not a.warmup and a.status == "failed"]),
            "metrics": {},
        }
        for key, values in metrics.items():
            summary["metrics"][key] = {
                "median": statistics.median(values) if values else None,
                "p10": _percentile(values, 0.10),
                "p90": _percentile(values, 0.90),
                "min": min(values) if values else None,
                "max": max(values) if values else None,
            }
        return summary
    finally:
        db.close()


def _run_wave(job_id: str, settings: AppSettings, config: BenchmarkCreate, warmup: bool, start_ordinal: int) -> int:
    workers = config.concurrency
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="llamalens-attempt") as pool:
        futures = {pool.submit(_measure, settings, config): start_ordinal + index for index in range(workers)}
        for future in as_completed(futures):
            ordinal = futures[future]
            if _is_cancelled(job_id):
                break
            try:
                _persist_attempt(job_id, ordinal, warmup, future.result(), None)
            except Exception as exc:
                _persist_attempt(job_id, ordinal, warmup, None, exc)
    return start_ordinal + workers


def _run_job(job_id: str) -> None:
    with EXECUTION_LOCK:
        _run_job_locked(job_id)


def _run_job_locked(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(BenchmarkJob, job_id)
        if job is None:
            return
        config = BenchmarkCreate.model_validate_json(job.config_json)
        settings = get_settings(db)
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()

    ordinal = 1
    try:
        for _ in range(config.warmup_runs):
            if _is_cancelled(job_id):
                break
            ordinal = _run_wave(job_id, settings, config, True, ordinal)
        for _ in range(config.repeat_runs):
            if _is_cancelled(job_id):
                break
            ordinal = _run_wave(job_id, settings, config, False, ordinal)
        summary = _summarize(job_id)
        db = SessionLocal()
        try:
            job = db.get(BenchmarkJob, job_id)
            if job is not None:
                job.status = "cancelled" if _is_cancelled(job_id) else "succeeded"
                job.summary_json = json.dumps(summary, ensure_ascii=False)
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
    except Exception as exc:
        db = SessionLocal()
        try:
            job = db.get(BenchmarkJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()
    finally:
        with _cancel_lock:
            _cancelled_jobs.discard(job_id)
