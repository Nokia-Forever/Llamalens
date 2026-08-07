from __future__ import annotations

from app.services.systemd import CommandResult


def single_payload(**overrides):
    payload = {
        "name": "Qwen Service",
        "description": "Qwen test service",
        "unit_name": "llamalens-qwen.service",
        "server_bin": "/opt/llama.cpp/llama-server",
        "service_user": "root",
        "service_group": "root",
        "working_directory": "/opt/llama.cpp",
        "host": "127.0.0.1",
        "port": 8088,
        "health_path": "/health",
        "request_path": "/completion",
        "mode": "single",
        "model_path": "/opt/models/qwen.gguf",
        "model_alias": "qwen",
        "models_dir": "",
        "models_preset": "",
        "models_max": 0,
        "models_autoload": False,
        "models": [],
        "custom_args_text": "--ctx-size 8192",
        "unit_extra_text": "RequiresMountsFor=/opt/models",
        "service_extra_text": "LimitNOFILE=1048576",
        "install_extra_text": "Alias=qwen.service",
    }
    payload.update(overrides)
    return payload


def test_preview_single_unit(client):
    response = client.post("/api/v1/services/preview-unit", json=single_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["unit_name"] == "llamalens-qwen.service"
    assert "[Unit]" in body["content"]
    assert "RequiresMountsFor=/opt/models" in body["content"]
    assert "--model /opt/models/qwen.gguf" in body["content"]
    assert "--alias qwen" in body["content"]
    assert "LimitNOFILE=1048576" in body["content"]


def test_preview_rejects_section_and_execstart(client):
    response = client.post("/api/v1/services/preview-unit", json=single_payload(unit_extra_text="[Service]"))
    assert response.status_code == 422
    response = client.post("/api/v1/services/preview-unit", json=single_payload(service_extra_text="ExecStart=/bin/false"))
    assert response.status_code == 422


def test_router_requires_aliases(client):
    payload = single_payload(
        mode="router", model_path="", model_alias="", models_dir="/opt/models/served",
        models_preset="/opt/llama.cpp/models-preset.ini", models_max=2, models_autoload=True, models=[],
    )
    response = client.post("/api/v1/services/preview-unit", json=payload)
    assert response.status_code == 422
    payload["models"] = [{"alias": "qwen", "model_path": "/opt/models/served/qwen.gguf", "display_name": "Qwen", "enabled": True}]
    response = client.post("/api/v1/services/preview-unit", json=payload)
    assert response.status_code == 200
    content = response.json()["content"]
    assert "--models-dir /opt/models/served" in content
    assert "--models-preset /opt/llama.cpp/models-preset.ini" in content
    assert "--models-max 2" in content
    assert "--models-autoload" in content


def test_deploy_and_delete_lifecycle(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMALENS_SYSTEMD_DIR", str(tmp_path / "systemd"))
    calls = []

    def fake_reload():
        calls.append(["systemctl", "daemon-reload"])
        return CommandResult(True, calls[-1], 0, "", "")

    def fake_action(unit_name, action, timeout=30):
        argv = ["systemctl", action, unit_name]
        calls.append(argv)
        return CommandResult(True, argv, 0, "ok", "")

    monkeypatch.setattr("app.services.llama_services.daemon_reload", fake_reload)
    monkeypatch.setattr("app.services.llama_services.run_unit_action", fake_action)
    created = client.post("/api/v1/services", json=single_payload()).json()
    deployed = client.post(f"/api/v1/services/{created['id']}/deploy")
    assert deployed.status_code == 200
    assert (tmp_path / "systemd" / "llamalens-qwen.service").is_file()
    assert calls[:3] == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable-now", "llamalens-qwen.service"],
        ["systemctl", "status", "llamalens-qwen.service"],
    ]
    deleted = client.delete(f"/api/v1/services/{created['id']}")
    assert deleted.status_code == 200
    assert not (tmp_path / "systemd" / "llamalens-qwen.service").exists()


def test_archive_and_restore(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LLAMALENS_SYSTEMD_DIR", str(tmp_path / "systemd"))
    monkeypatch.setenv("LLAMALENS_DATA_DIR", str(tmp_path / "data"))

    def fake_reload():
        return CommandResult(True, ["systemctl", "daemon-reload"], 0, "", "")

    def fake_action(unit_name, action, timeout=30):
        return CommandResult(True, ["systemctl", action, unit_name], 0, "", "")

    monkeypatch.setattr("app.services.llama_services.daemon_reload", fake_reload)
    monkeypatch.setattr("app.services.llama_services.run_unit_action", fake_action)
    created = client.post("/api/v1/services", json=single_payload()).json()
    client.post(f"/api/v1/services/{created['id']}/deploy")
    archived = client.post(f"/api/v1/services/{created['id']}/archive")
    assert archived.status_code == 200
    assert not (tmp_path / "systemd" / "llamalens-qwen.service").exists()
    assert (tmp_path / "data" / "archive" / "services" / created["id"] / "llamalens-qwen.service").is_file()
    restored = client.post(f"/api/v1/services/{created['id']}/restore")
    assert restored.status_code == 200
    assert (tmp_path / "systemd" / "llamalens-qwen.service").is_file()
