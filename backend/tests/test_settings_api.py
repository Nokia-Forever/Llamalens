from __future__ import annotations


def test_settings_round_trip(client):
    current = client.get("/api/v1/settings")
    assert current.status_code == 200
    payload = current.json()
    payload["llama_service_name"] = "my-llama.service"
    payload["model_roots"] = ["/srv/models", "/data/models"]
    updated = client.put("/api/v1/settings", json=payload)
    assert updated.status_code == 200
    assert updated.json()["llama_service_name"] == "my-llama.service"
    assert client.get("/api/v1/settings").json()["model_roots"] == ["/srv/models", "/data/models"]


def test_settings_reject_arbitrary_control_command(client):
    payload = client.get("/api/v1/settings").json()
    payload["service_control_command"] = "python systemctl"
    response = client.put("/api/v1/settings", json=payload)
    assert response.status_code == 422
