from agent_quality import model_cost
from cloudbuild_demo import config
from cloudrun_demo import manifest


def test_metering_requires_usage_and_price_for_every_attempt():
    rates = {"model": [1.0, 2.0]}
    known = {"model": "model", "input": 300, "output": 100}
    assert model_cost([{"model_calls": [known]}], rates)[1] == 0.0005
    assert model_cost([{"model_calls": [known, dict(known, output=None)]}], rates)[1] is None
    assert model_cost([{"model_calls": [known]}], {})[1] is None
    assert model_cost([{}], {})[1] == 0


def test_staging_manifest_is_single_ingress_with_vertex_and_durable_evidence(monkeypatch):
    for key in (
        "GOOGLE_CLOUD_PROJECT",
        "IMAGE_REGISTRY",
        "RELEASE",
        "RUNTIME_SERVICE_ACCOUNT",
        "OIDC_AUDIENCE",
        "DOCUMENT_BUCKET",
        "GEMINI_MODEL",
    ):
        monkeypatch.setenv(key, "test")
    monkeypatch.setenv("OIDC_ISSUER", "https://login.example.test")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://login.example.test/keys")
    spec = manifest()["spec"]["template"]["spec"]
    containers = {c["name"]: c for c in spec["containers"]}
    assert set(config()["images"]) == {c["image"] for c in containers.values()}
    assert [name for name, c in containers.items() if c.get("ports")] == ["gateway"]
    assert all(c.get("startupProbe") for name, c in containers.items() if name != "gateway")
    assert {"name": "GOOGLE_GENAI_USE_VERTEXAI", "value": "true"} in containers["agents"]["env"]
    assert containers["core"]["volumeMounts"][0]["name"] == spec["volumes"][0]["name"]
