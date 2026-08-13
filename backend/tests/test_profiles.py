from __future__ import annotations

from pathlib import Path

from app.database import SessionLocal
from app.schemas import AppSettings, CatalogArgumentInput, ProfileCreate
from app.services.arguments import seed_builtin_catalog
from app.services.profiles_service import create_profile, serialize_profile, update_profile


def test_profile_crud_and_argv(tmp_path: Path):
    model = tmp_path / "Qwen-Test-Q4_K_M.gguf"
    model.write_bytes(b"GGUF")
    settings = AppSettings(model_roots=[str(tmp_path)], llama_server_bin="/opt/llama-server")
    db = SessionLocal()
    try:
        seed_builtin_catalog(db)
        profile = create_profile(
            db,
            settings,
            ProfileCreate(
                name="Qwen test",
                model_path=str(model),
                model_alias="qwen-test",
                catalog_args=[CatalogArgumentInput(flag="--ctx-size", value="8192")],
                custom_args_text="-np 1",
            ),
        )
        output = serialize_profile(db, settings, profile)
        assert output.final_argv[-4:] == ["--ctx-size", "8192", "-np", "1"]
        updated = update_profile(
            db,
            settings,
            profile,
            ProfileCreate(name="Updated", model_path=str(model), model_alias="updated", custom_args_text="--flash-attn auto"),
        )
        assert updated.name == "Updated"
    finally:
        db.close()


def test_list_profiles_returns_paginated_envelope(client, tmp_path):
    model = tmp_path / "Qwen-List-Q4_K_M.gguf"
    model.write_bytes(b"GGUF")
    settings = client.get("/api/v1/settings").json()
    settings["model_roots"] = [str(tmp_path)]
    assert client.put("/api/v1/settings", json=settings).status_code == 200
    for i in range(3):
        resp = client.post("/api/v1/profiles", json={
            "name": f"Profile {i}", "mode": "single", "model_path": str(model), "model_alias": f"alias-{i}",
            "models_dir": "", "models_preset": "", "models_max": 0, "models_autoload": False,
            "models": [], "catalog_args": [], "custom_args_text": "", "labels": {},
        })
        assert resp.status_code == 200, resp.text
    body = client.get("/api/v1/profiles").json()
    assert set(body.keys()) == {"items", "total", "offset", "limit"}
    assert body["total"] == 3
    assert len(body["items"]) == 3


def test_list_profiles_flags_loaded_once_per_request(client, monkeypatch, tmp_path):
    import app.api.profiles as profiles_api
    model = tmp_path / "Qwen-Flags-Q4_K_M.gguf"
    model.write_bytes(b"GGUF")
    settings = client.get("/api/v1/settings").json()
    settings["model_roots"] = [str(tmp_path)]
    assert client.put("/api/v1/settings", json=settings).status_code == 200
    for i in range(4):
        client.post("/api/v1/profiles", json={
            "name": f"Flags {i}", "mode": "single", "model_path": str(model), "model_alias": f"flags-{i}",
            "models_dir": "", "models_preset": "", "models_max": 0, "models_autoload": False,
            "models": [], "catalog_args": [], "custom_args_text": "", "labels": {},
        })
    known_calls = {"n": 0}
    canon_calls = {"n": 0}
    real_known = profiles_api.known_flags
    real_canon = profiles_api.canonical_flags

    def counting_known(db):
        known_calls["n"] += 1
        return real_known(db)

    def counting_canon(db):
        canon_calls["n"] += 1
        return real_canon(db)

    monkeypatch.setattr(profiles_api, "known_flags", counting_known)
    monkeypatch.setattr(profiles_api, "canonical_flags", counting_canon)
    body = client.get("/api/v1/profiles?limit=200").json()
    assert body["total"] == 4
    assert known_calls["n"] == 1
    assert canon_calls["n"] == 1
