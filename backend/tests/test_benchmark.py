from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.database import SessionLocal
from app.models import BenchmarkAttempt, BenchmarkJob, LlamaService
from app.schemas import AppSettings, BenchmarkCreate, LaunchConfig, LlamaServiceCreate
from app.services import benchmark


class FakeResponse:
    def raise_for_status(self):
        return None

    def iter_lines(self):
        return iter([
            'data: {"content":""}',
            'data: {"content":"Hello"}',
            'data: {"content":" world"}',
            'data: {"stop":true,"timings":{"prompt_n":12,"prompt_per_second":240.5,"predicted_n":2,"predicted_per_second":31.25}}',
            'data: [DONE]',
        ])


class FakeStream:
    def __enter__(self): return FakeResponse()
    def __exit__(self, *_args): return None


class FakeClient:
    def __init__(self, **_kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def stream(self, *_args, **_kwargs): return FakeStream()


class FakeSampler:
    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def summary(self): return {"sample_count": 0, "nvidia": []}


def test_stream_measurement_extracts_ttft_and_server_timings(monkeypatch):
    ticks = iter([10.0, 10.2, 10.4, 10.5])
    monkeypatch.setattr(benchmark.httpx, "Client", FakeClient)
    monkeypatch.setattr(benchmark, "_ResourceSampler", FakeSampler)
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(ticks))
    result = benchmark._measure(AppSettings(), BenchmarkCreate(prompt="hello", max_tokens=2))
    assert result["ttft_ms"] == pytest.approx(200)
    assert result["prefill_tps"] == 240.5
    assert result["decode_tps"] == 31.25
    assert result["client_decode_tps"] == pytest.approx(5)
    assert result["prompt_tokens"] == 12
    assert result["predicted_tokens"] == 2
    assert result["measurement_mode"] == "stream"
    assert benchmark.extract_output_text(result["raw"]) == "Hello world"


def test_extract_output_text_supports_paired_response():
    payload = {
        "stream": {"events": [{"content": "paired"}, {"content": " output"}]},
        "paired": {"content": "fallback"},
    }
    assert benchmark.extract_output_text(payload) == "paired output"


def test_extra_params_cannot_override_core_measurement_fields():
    config = BenchmarkCreate(
        prompt="real prompt",
        max_tokens=16,
        temperature=0.2,
        extra_params={"prompt": "wrong", "n_predict": 999, "stream": False, "top_p": 0.9},
    )
    payload = benchmark._base_payload(config, stream=True)
    assert payload["prompt"] == "real prompt"
    assert payload["n_predict"] == 16
    assert payload["stream"] is True
    assert payload["top_p"] == 0.9


def test_model_alias_is_added_to_benchmark_request():
    payload = benchmark._base_payload(BenchmarkCreate(prompt="hello", model_alias="qwen-router"), stream=True)
    assert payload["model"] == "qwen-router"


def test_repeat_delay_validation_and_default():
    assert BenchmarkCreate(prompt="hello").repeat_delay_ms == 0
    assert BenchmarkCreate(prompt="hello", repeat_delay_ms=600000).repeat_delay_ms == 600000
    with pytest.raises(ValidationError):
        BenchmarkCreate(prompt="hello", repeat_delay_ms=-1)
    with pytest.raises(ValidationError):
        BenchmarkCreate(prompt="hello", repeat_delay_ms=600001)


def test_repeat_delay_only_runs_between_formal_waves(monkeypatch):
    db = SessionLocal()
    try:
        config = BenchmarkCreate(prompt="hello", warmup_runs=2, repeat_runs=3, repeat_delay_ms=250)
        job = BenchmarkJob(id="delayed-job", name="delayed", status="queued", config_json=config.model_dump_json())
        db.add(job)
        db.commit()
    finally:
        db.close()

    waves = []
    waits = []

    def fake_wave(_job_id, _settings, _config, warmup, ordinal):
        waves.append(warmup)
        return ordinal + 1

    def fake_wait(_job_id, delay_ms):
        waits.append(delay_ms)
        return True

    monkeypatch.setattr(benchmark, "_run_wave", fake_wave)
    monkeypatch.setattr(benchmark, "_wait_repeat_delay", fake_wait)
    benchmark._run_job_locked("delayed-job")
    assert waves == [True, True, False, False, False]
    assert waits == [250, 250]


def test_repeat_delay_wait_is_cancellable(monkeypatch):
    job_id = "cancel-delay"
    benchmark._cancelled_jobs.discard(job_id)
    ticks = iter([0.0, 0.0])
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(benchmark.time, "sleep", lambda _seconds: benchmark.cancel_benchmark(job_id))
    try:
        assert benchmark._wait_repeat_delay(job_id, 1000) is False
    finally:
        benchmark._cancelled_jobs.discard(job_id)


def test_benchmark_requires_applied_service(monkeypatch):
    db = SessionLocal()
    try:
        service = LlamaService(
            id="service-1", name="one", unit_name="llamalens-one.service",
            unit_path="/etc/systemd/system/llamalens-one.service", server_bin="/opt/llama-server",
            host="127.0.0.1", port=8080,
        )
        db.add(service)
        db.commit()
        monkeypatch.setattr(benchmark.BENCHMARK_EXECUTOR, "submit", lambda *_args, **_kwargs: None)
        with pytest.raises(ValueError, match="尚未成功部署"):
            benchmark.create_benchmark_job(db, BenchmarkCreate(prompt="hello", service_id=service.id, model_alias="one"))
        service.applied_launch_config_json = LaunchConfig(mode="single", model_path="/models/one.gguf", model_alias="one").model_dump_json()
        service.applied_service_config_json = LlamaServiceCreate(
            name="one", unit_name="llamalens-one.service", server_bin="/opt/llama-server",
            host="127.0.0.1", port=9000,
        ).model_dump_json()
        db.commit()
        job = benchmark.create_benchmark_job(db, BenchmarkCreate(prompt="hello", service_id=service.id, model_alias="one", repeat_delay_ms=125))
        assert job.service_id == service.id
        snapshot = json.loads(job.config_json)
        assert snapshot["service_snapshot"]["port"] == 9000
        assert snapshot["repeat_delay_ms"] == 125
    finally:
        db.close()


def _stored_job(job_id: str, status: str = "succeeded") -> BenchmarkJob:
    return BenchmarkJob(
        id=job_id,
        name=job_id,
        status=status,
        config_json=BenchmarkCreate(prompt="hello").model_dump_json(),
        summary_json="{}",
    )


def test_attempt_detail_returns_generated_text(client):
    db = SessionLocal()
    try:
        job = _stored_job("detail-job")
        attempt = BenchmarkAttempt(
            job=job, ordinal=1, warmup=False, status="succeeded", measurement_mode="stream",
            request_json=json.dumps({"prompt": "hello"}),
            raw_response_json=json.dumps({"events": [{"content": "model"}, {"content": " answer"}]}),
            resource_json=json.dumps({"sample_count": 1}),
        )
        db.add_all([job, attempt])
        db.commit()
        attempt_id = attempt.id
    finally:
        db.close()
    response = client.get(f"/api/v1/benchmarks/detail-job/attempts/{attempt_id}")
    assert response.status_code == 200
    assert response.json()["output_text"] == "model answer"
    assert response.json()["request"] == {"prompt": "hello"}


def test_delete_single_cascades_attempts(client):
    db = SessionLocal()
    try:
        job = _stored_job("delete-one")
        attempt = BenchmarkAttempt(
            job=job, ordinal=1, request_json="{}", raw_response_json="{}", resource_json="{}",
        )
        db.add_all([job, attempt])
        db.commit()
        attempt_id = attempt.id
    finally:
        db.close()
    response = client.delete("/api/v1/benchmarks/delete-one")
    assert response.status_code == 200
    db = SessionLocal()
    try:
        assert db.get(BenchmarkJob, "delete-one") is None
        assert db.get(BenchmarkAttempt, attempt_id) is None
    finally:
        db.close()


def test_bulk_delete_is_atomic_and_rejects_running_jobs(client):
    db = SessionLocal()
    try:
        db.add_all([_stored_job("finished"), _stored_job("active", "running")])
        db.commit()
    finally:
        db.close()
    blocked = client.post("/api/v1/benchmarks/bulk-delete", json={"ids": ["finished", "active"]})
    assert blocked.status_code == 409
    db = SessionLocal()
    try:
        assert db.get(BenchmarkJob, "finished") is not None
        active = db.get(BenchmarkJob, "active")
        assert active is not None
        active.status = "cancelled"
        db.commit()
    finally:
        db.close()
    deleted = client.post("/api/v1/benchmarks/bulk-delete", json={"ids": ["finished", "active"]})
    assert deleted.status_code == 200
    assert set(deleted.json()["deleted_ids"]) == {"finished", "active"}
