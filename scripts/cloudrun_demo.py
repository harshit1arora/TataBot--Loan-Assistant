"""Render a Cloud Run staging service. Secret values stay in Secret Manager."""

import json
import os


def env(**values):
    return [{"name": k, "value": v} for k, v in values.items()]


def secret(variable, name):
    return {
        "name": variable,
        "valueFrom": {"secretKeyRef": {"name": "tatabot-" + name, "key": "latest"}},
    }


def manifest():
    project, registry, release, account, issuer, audience, bucket, model = [
        os.environ[key]
        for key in (
            "GOOGLE_CLOUD_PROJECT",
            "IMAGE_REGISTRY",
            "RELEASE",
            "RUNTIME_SERVICE_ACCOUNT",
            "OIDC_ISSUER",
            "OIDC_AUDIENCE",
            "DOCUMENT_BUCKET",
            "GEMINI_MODEL",
        )
    ]
    if not issuer.startswith("https://"):
        raise ValueError("OIDC_ISSUER must use HTTPS")
    from urllib.parse import urlsplit

    origin = urlsplit(issuer)
    core_url = "http://127.0.0.1:8000"
    crm = "http://127.0.0.1:8002"
    definitions = {}

    def add(name, settings, module=None, port=None):
        item = {
            "name": name,
            "image": f"{registry}/{name}:{release}",
            "env": settings,
            "resources": {"limits": {"cpu": "1", "memory": "512Mi"}},
        }
        if module:
            item.update(
                command=["uvicorn"],
                args=[module + ".main:app", "--host", "0.0.0.0", "--port", str(port)],
            )
        definitions[name] = item
        return item

    gateway = add(
        "gateway",
        env(
            CORE_UPSTREAM="127.0.0.1:8000",
            CONVERSATION_UPSTREAM="127.0.0.1:8001",
            OIDC_CONNECT_ORIGIN=f"{origin.scheme}://{origin.netloc}",
        ),
    )
    gateway["ports"] = [{"containerPort": 8080}]
    jwt = secret("JWT_SECRET", "jwt")
    redis = secret("REDIS_URL", "redis-url")
    agents = secret("AGENT_SERVICE_TOKEN", "agent-token")
    crm_token = secret("MOCK_CRM_TOKEN", "crm-token")
    offers = secret("MOCK_OFFERMART_TOKEN", "offer-token")
    core = add(
        "core",
        env(
            ENV="production",
            ALLOW_DEMO_AUTH="false",
            OIDC_ISSUER=issuer,
            OIDC_AUDIENCE=audience,
            OIDC_JWKS_URL=os.environ["OIDC_JWKS_URL"],
            STORAGE_DIR="/evidence",
            STORAGE_BACKEND="local",
        )
        + [
            jwt,
            redis,
            secret("DATABASE_URL", "core-db"),
            secret("SERVICE_CLIENT_SECRET", "core-client"),
            secret("OIDC_REVIEWER_SUBJECTS", "reviewers"),
        ],
    )
    core["volumeMounts"] = [{"name": "evidence", "mountPath": "/evidence"}]
    add(
        "conversation",
        env(
            ENV="production",
            LLM_ENABLED="false",
            CORE_BASE_URL=core_url,
            AGENTS_BASE_URL="http://127.0.0.1:8004",
            AGENTS_ENABLED="true",
        )
        + [
            jwt,
            redis,
            agents,
            secret("DATABASE_URL", "conversation-db"),
            secret("CORE_CLIENT_SECRET", "core-client"),
        ],
    )
    add("mock-crm", [crm_token], "mock_crm", 8002)
    add("mock-offermart", env(CRM_BASE_URL=crm) + [crm_token, offers], "mock_offermart", 8003)
    add(
        "mcp-server",
        env(CORE_BASE_URL=core_url, CRM_BASE_URL=crm, OFFERMART_BASE_URL="http://127.0.0.1:8003")
        + [secret("CORE_CLIENT_SECRET", "core-client"), crm_token, offers],
    )
    add(
        "agents",
        env(
            LLM_PROVIDER="gemini",
            GOOGLE_GENAI_USE_VERTEXAI="true",
            GOOGLE_CLOUD_PROJECT=project,
            GOOGLE_CLOUD_LOCATION=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            GEMINI_MODEL=model,
            MAX_WORKERS_PER_TURN="4",
            MCP_TRANSPORT="http",
            MCP_URL="http://127.0.0.1:8765/mcp",
        )
        + [redis, agents],
    )
    ports = {
        "core": 8000,
        "conversation": 8001,
        "mock-crm": 8002,
        "mock-offermart": 8003,
        "agents": 8004,
        "mcp-server": 8765,
    }
    for name, port in ports.items():
        definitions[name]["startupProbe"] = {
            "tcpSocket": {"port": port},
            "periodSeconds": 3,
            "failureThreshold": 60,
        }
    return {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {"name": "tatabot-staging"},
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "run.googleapis.com/execution-environment": "gen2",
                        "autoscaling.knative.dev/maxScale": "2",
                        "run.googleapis.com/container-dependencies": json.dumps(
                            {"gateway": list(ports)}
                        ),
                    }
                },
                "spec": {
                    "serviceAccountName": account,
                    "containerConcurrency": 8,
                    "containers": list(definitions.values()),
                    "volumes": [
                        {
                            "name": "evidence",
                            "csi": {
                                "driver": "gcsfuse.run.googleapis.com",
                                "volumeAttributes": {
                                    "bucketName": bucket,
                                    "mountOptions": "uid=10001,gid=10001",
                                },
                            },
                        }
                    ],
                },
            }
        },
    }


if __name__ == "__main__":
    print(json.dumps(manifest(), indent=2))
