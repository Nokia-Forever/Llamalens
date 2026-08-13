from __future__ import annotations

from app.services.systemd import CommandResult


def service_payload(name="Qwen Service", unit_name="llamalens-qwen.service", port=8088, **overrides):
    payload = {
        "name": name,
        "description": "Qwen test service",
        "unit_name": unit_name,
        "server_bin": "/opt/llama.cpp/llama-server",
        "service_user": "root",
        "service_group": "root",
        "working_directory": "/opt/llama.cpp",
        "host": "127.0.0.1",
        "port": port,
        "health_path": "/health",
        "request_path": "/completion",
        "unit_extra_text": "RequiresMountsFor=/opt/models",
        "service_extra_text": "LimitNOFILE=1048576",
        "install_extra_text": "Alias=qwen.service",
    }
    payload.update(overrides)
    return payload


def configure_models(client, tmp_path):
    model = tmp_path / "qwen.gguf"
    model.write_bytes(b"GGUF")
    settings = client.get("/api/v1/settings").json()
    settings["model_roots"] = [str(tmp_path)]
    assert client.put("/api/v1/settings", json=settings).status_code == 200
    return model


def create_profile(client, model, name="Qwen profile", alias="qwen"):
    response = client.post("/api/v1/profiles", json={
        "name": name, "mode": "single", "model_path": str(model), "model_alias": alias,
        "models_dir": "", "models_preset": "", "models_max": 0, "models_autoload": False,
        "models": [], "catalog_args": [{"flag": "--ctx-size", "value": "8192"}],
        "custom_args_text": "--gpu-layers all", "labels": {},
    })
    assert response.status_code == 200, response.text
    return response.json()


def import_profile(client, service_id, profile_id):
    response = client.post(f"/api/v1/services/{service_id}/select-profile", json={"profile_id": profile_id})
    assert response.status_code == 200, response.text
    return response.json()


def test_profile_copy_is_independent_per_service(client, tmp_path):
    model = configure_models(client, tmp_path)
    profile = create_profile(client, model)
    first = client.post("/api/v1/services", json=service_payload()).json()
    second = client.post("/api/v1/services", json=service_payload("Second", "llamalens-second.service", 8089)).json()
    first = import_profile(client, first["id"], profile["id"])
    second = import_profile(client, second["id"], profile["id"])
    changed = {**first["draft_launch_config"], "model_alias": "qwen-local"}
    assert client.patch(f"/api/v1/services/{first['id']}/launch-config", json=changed).status_code == 200
    second_after = client.get(f"/api/v1/services/{second['id']}").json()
    assert second_after["draft_launch_config"]["model_alias"] == "qwen"
    profile_update = {key: value for key, value in profile.items() if key in {
        "name", "mode", "model_path", "model_alias", "models_dir", "models_preset", "models_max",
        "models_autoload", "models", "catalog_args", "custom_args_text", "labels",
    }}
    profile_update["model_alias"] = "template-updated"
    assert client.put(f"/api/v1/profiles/{profile['id']}", json=profile_update).status_code == 200
    assert client.get(f"/api/v1/services/{second['id']}").json()["draft_launch_config"]["model_alias"] == "qwen"


def test_preview_uses_service_draft(client, tmp_path):
    model = configure_models(client, tmp_path)
    profile = create_profile(client, model)
    service = client.post("/api/v1/services", json=service_payload()).json()
    import_profile(client, service["id"], profile["id"])
    response = client.post(f"/api/v1/services/{service['id']}/preview-unit")
    assert response.status_code == 200
    content = response.json()["content"]
    argv = response.json()["argv"]
    assert "[Unit]" in content
    assert "RequiresMountsFor=/opt/models" in content
    assert argv[argv.index("--model") + 1] == str(model)
    assert argv[argv.index("--alias") + 1] == "qwen"
    assert argv[argv.index("--ctx-size") + 1] == "8192"


def test_preview_rejects_invalid_systemd_section(client, tmp_path):
    model = configure_models(client, tmp_path)
    profile = create_profile(client, model)
    service = client.post("/api/v1/services", json=service_payload(service_extra_text="ExecStart=/bin/false")).json()
    import_profile(client, service["id"], profile["id"])
    response = client.post(f"/api/v1/services/{service['id']}/preview-unit")
    assert response.status_code == 422


def test_router_profile_preview(client, tmp_path):
    model = configure_models(client, tmp_path)
    response = client.post("/api/v1/profiles", json={
        "name": "Router", "mode": "router", "model_path": "", "model_alias": "",
        "models_dir": str(tmp_path), "models_preset": "/opt/llama.cpp/models-preset.ini",
        "models_max": 2, "models_autoload": True,
        "models": [{"alias": "qwen", "model_path": str(model), "display_name": "Qwen", "enabled": True}],
        "catalog_args": [], "custom_args_text": "", "labels": {},
    })
    assert response.status_code == 200, response.text
    service = client.post("/api/v1/services", json=service_payload()).json()
    import_profile(client, service["id"], response.json()["id"])
    preview = client.post(f"/api/v1/services/{service['id']}/preview-unit").json()
    argv = preview["argv"]
    assert argv[argv.index("--models-dir") + 1] == str(tmp_path)
    assert argv[argv.index("--models-preset") + 1] == "/opt/llama.cpp/models-preset.ini"
    assert argv[argv.index("--models-max") + 1] == "2"
    assert "--models-autoload" in argv


def test_deploy_updates_applied_only_after_success(client, monkeypatch, tmp_path):
    model = configure_models(client, tmp_path)
    profile = create_profile(client, model)
    second_profile = create_profile(client, model, name="Second profile", alias="qwen-next")
    monkeypatch.setenv("LLAMALENS_SYSTEMD_DIR", str(tmp_path / "systemd"))
    calls = []
    action_succeeds = True

    def fake_reload():
        calls.append(["systemctl", "daemon-reload"])
        return CommandResult(True, calls[-1], 0, "", "")

    def fake_action(unit_name, action, timeout=30):
        argv = ["systemctl", action, unit_name]
        calls.append(argv)
        ok = action_succeeds or action != "enable-now"
        return CommandResult(ok, argv, 0 if ok else 1, "ok" if ok else "", "" if ok else "failed")

    monkeypatch.setattr("app.services.llama_services.daemon_reload", fake_reload)
    monkeypatch.setattr("app.services.llama_services.run_unit_action", fake_action)
    service = client.post("/api/v1/services", json=service_payload()).json()
    import_profile(client, service["id"], profile["id"])
    deployed = client.post(f"/api/v1/services/{service['id']}/deploy")
    assert deployed.status_code == 200 and deployed.json()["ok"]
    after = client.get(f"/api/v1/services/{service['id']}").json()
    assert after["applied_launch_config"]["model_alias"] == "qwen"
    assert after["applied_source_profile_id"] == profile["id"]
    assert not after["has_pending_changes"]
    assert (tmp_path / "systemd" / "llamalens-qwen.service").is_file()

    changed_base = service_payload(port=8090)
    assert client.patch(f"/api/v1/services/{service['id']}", json=changed_base).status_code == 200
    after_base_change = client.get(f"/api/v1/services/{service['id']}").json()
    assert after_base_change["applied_service_config"]["port"] == 8088
    assert after_base_change["has_pending_changes"]

    import_profile(client, service["id"], second_profile["id"])
    action_succeeds = False
    failed = client.post(f"/api/v1/services/{service['id']}/deploy")
    assert failed.status_code == 200 and not failed.json()["ok"]
    after_failed = client.get(f"/api/v1/services/{service['id']}").json()
    assert after_failed["source_profile_id"] == second_profile["id"]
    assert after_failed["draft_launch_config"]["model_alias"] == "qwen-next"
    assert after_failed["applied_source_profile_id"] == profile["id"]
    assert after_failed["applied_launch_config"]["model_alias"] == "qwen"
    assert after_failed["applied_service_config"]["port"] == 8088
    assert after_failed["has_pending_changes"]


def test_archive_and_restore(client, monkeypatch, tmp_path):
    model = configure_models(client, tmp_path)
    profile = create_profile(client, model)
    monkeypatch.setenv("LLAMALENS_SYSTEMD_DIR", str(tmp_path / "systemd"))
    monkeypatch.setenv("LLAMALENS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("app.services.llama_services.daemon_reload", lambda: CommandResult(True, ["systemctl", "daemon-reload"], 0, "", ""))
    monkeypatch.setattr("app.services.llama_services.run_unit_action", lambda unit_name, action, timeout=30: CommandResult(True, ["systemctl", action, unit_name], 0, "", ""))
    service = client.post("/api/v1/services", json=service_payload()).json()
    import_profile(client, service["id"], profile["id"])
    client.post(f"/api/v1/services/{service['id']}/deploy")
    assert client.post(f"/api/v1/services/{service['id']}/archive").status_code == 200
    assert (tmp_path / "data" / "archive" / "services" / service["id"] / "llamalens-qwen.service").is_file()
    assert client.post(f"/api/v1/services/{service['id']}/restore").status_code == 200
    assert (tmp_path / "systemd" / "llamalens-qwen.service").is_file()


def test_list_services_with_status_batches_systemctl(client, monkeypatch, tmp_path):
    import json as _json
    from app.services import systemd

    model = configure_models(client, tmp_path)
    profile = create_profile(client, model)
    monkeypatch.setenv("LLAMALENS_SYSTEMD_DIR", str(tmp_path / "systemd"))
    monkeypatch.setattr("app.services.llama_services.daemon_reload", lambda: CommandResult(True, ["systemctl", "daemon-reload"], 0, "", ""))
    monkeypatch.setattr("app.services.llama_services.run_unit_action", lambda unit_name, action, timeout=30: CommandResult(True, ["systemctl", action, unit_name], 0, "", ""))
    first = client.post("/api/v1/services", json=service_payload()).json()
    second = client.post("/api/v1/services", json=service_payload("Second", "llamalens-second.service", 8089)).json()
    import_profile(client, first["id"], profile["id"])
    import_profile(client, second["id"], profile["id"])
    client.post(f"/api/v1/services/{first['id']}/deploy")
    client.post(f"/api/v1/services/{second['id']}/deploy")

    run_calls: list[list[str]] = []

    class FakeCompleted:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(argv, **kwargs):
        run_calls.append(list(argv))
        if "list-units" in argv:
            units = [
                {"unit": "llamalens-qwen.service", "active": "active", "sub": "running", "description": "Qwen"},
                {"unit": "llamalens-second.service", "active": "inactive", "sub": "dead", "description": "Second"},
            ]
            return FakeCompleted(0, _json.dumps(units), "")
        return FakeCompleted(0, "", "")

    monkeypatch.setattr(systemd.subprocess, "run", fake_run)

    body = client.get("/api/v1/services?with_status=true").json()
    list_units_calls = [c for c in run_calls if "list-units" in c]
    assert len(list_units_calls) == 1
    by_id = {s["id"]: s for s in body}
    assert by_id[first["id"]]["status"]["ok"] is True
    assert by_id[second["id"]]["status"]["ok"] is False
