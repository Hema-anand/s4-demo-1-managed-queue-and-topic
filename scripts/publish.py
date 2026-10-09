"""Builds and publishes the application's container image.
Authenticates Docker to Floci's local registry.
Pushes the image with the current Git commit SHA and verifies its presence.
"""

import os
import re
import subprocess
from urllib.parse import urlparse

from scripts.local_cloud import REPOSITORY, ROOT, aws


def main():
    sha = os.environ.get("GITHUB_SHA") or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected a full 40-character Git commit SHA.")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if sha != actual:
        raise ValueError("The image tag must match the checked-out commit.")
    uri = aws("ecr", "describe-repositories", "--repository-names", REPOSITORY)["repositories"][0]["repositoryUri"]
    registry = uri.split("/", 1)[0]
    host = urlparse("http://" + registry).hostname or ""
    if host not in {"localhost", "127.0.0.1"} and not host.endswith(".localhost"):
        raise ValueError("Expected a local Floci registry URI. Check the Floci version and configuration.")
    image = f"{uri}:{sha}"
    print(f"Building {image}", flush=True)
    subprocess.run(["docker", "build", "--tag", image, str(ROOT)], check=True)
    token = aws("ecr", "get-authorization-token")["authorizationData"][0]["authorizationToken"]
    import base64
    username, password = base64.b64decode(token).decode().split(":", 1)
    subprocess.run(["docker", "login", "--username", username, "--password-stdin", registry],
                   input=password, text=True, check=True)
    subprocess.run(["docker", "push", image], check=True)
    metadata = aws("ecr", "describe-images", "--repository-name", REPOSITORY,
                   "--image-ids", f"imageTag={sha}")
    if not metadata.get("imageDetails"):
        raise RuntimeError("The pushed SHA tag is absent from ECR.")
    print(f"Published image digest: {metadata['imageDetails'][0]['imageDigest']}")
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
            stream.write(f"IMAGE_URI={image}\n")
    print(f"IMAGE_URI={image}")


if __name__ == "__main__":
    main()
