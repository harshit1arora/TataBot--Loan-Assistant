"""Render a Cloud Build config for the seven staging images from this checkout."""

import json
import os


def config():
    base = os.environ["IMAGE_REGISTRY"]
    tag = os.environ["RELEASE"]
    steps, images = [], []
    for name in (
        "gateway",
        "core",
        "conversation",
        "agents",
        "mcp-server",
        "mock-crm",
        "mock-offermart",
    ):
        image = f"{base}/{name}:{tag}"
        args = ["build", "-t", image]
        if name == "gateway":
            args += [
                "--build-arg",
                "VITE_OIDC_ISSUER=" + os.environ["OIDC_ISSUER"],
                "--build-arg",
                "VITE_OIDC_CLIENT_ID=" + os.environ["OIDC_AUDIENCE"],
                "apps/web",
            ]
        else:
            args.append("services/" + name)
        steps.append(
            {"name": "gcr.io/cloud-builders/docker", "args": args, "id": name, "waitFor": ["-"]}
        )
        images.append(image)
    return {"steps": steps, "images": images, "timeout": "2400s"}


if __name__ == "__main__":
    print(json.dumps(config(), indent=2))
