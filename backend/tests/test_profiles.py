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
