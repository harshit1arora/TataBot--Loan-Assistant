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
    assert all(
        c.get("startupProbe") for name, c in containers.items() if name not in ("gateway", "worker")
    )
    assert {"name": "GOOGLE_GENAI_USE_VERTEXAI", "value": "true"} in containers["agents"]["env"]
    assert containers["core"]["volumeMounts"][0]["name"] == spec["volumes"][0]["name"]


def test_staging_telemetry_is_configured_with_secret_references(monkeypatch):
    for key in ("GOOGLE_CLOUD_PROJECT", "IMAGE_REGISTRY", "RELEASE", "RUNTIME_SERVICE_ACCOUNT",
                "OIDC_AUDIENCE", "DOCUMENT_BUCKET", "GEMINI_MODEL"):
        monkeypatch.setenv(key, "test")
    monkeypatch.setenv("OIDC_ISSUER", "https://login.example.test")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://login.example.test/keys")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://collector.example.test/v1/traces")
    monkeypatch.setenv("OTEL_AUTH_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.test")
    containers = {c["name"]: c for c in manifest()["spec"]["template"]["spec"]["containers"]}
    for name in ("core", "conversation", "agents"):
        env = {entry["name"]: entry for entry in containers[name]["env"]}
        assert env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"]["value"].endswith("/v1/traces")
        assert env["OTEL_EXPORTER_OTLP_HEADERS"]["valueFrom"]["secretKeyRef"]["name"] == "tatabot-otel-headers"
    agent_env = {entry["name"]: entry for entry in containers["agents"]["env"]}
    assert agent_env["LANGFUSE_SECRET_KEY"]["valueFrom"]["secretKeyRef"]["name"] == "tatabot-langfuse-secret"
