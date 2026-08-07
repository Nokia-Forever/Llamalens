from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import Profile, SwitchJob
from app.schemas import AppSettings, BenchmarkCreate
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


def test_benchmark_rejected_while_profile_switch_is_pending(monkeypatch):
    db = SessionLocal()
    try:
        profile = Profile(id="profile-1", name="one", model_path="/models/one.gguf")
        db.add(profile)
        db.add(SwitchJob(id="switch-1", profile_id=profile.id, status="queued"))
        db.commit()
        monkeypatch.setattr(benchmark.BENCHMARK_EXECUTOR, "submit", lambda *_args, **_kwargs: None)
        with pytest.raises(ValueError, match="正在切换"):
            benchmark.create_benchmark_job(db, BenchmarkCreate(prompt="hello"))
    finally:
        db.close()
