"""Shared AWS CLI helpers. Every request explicitly targets local Floci."""

"""Provides shared helpers for communicating with local Floci services.
Checks the endpoint and region, and retrieves the execution-role ARN.
Saves generated deployment configuration and evidence locally.
"""

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "application-service"
LOG_GROUP = "/ecs/application-service"
CLUSTER = "sprint4-cluster"
SERVICE = "application-service"
VPC_NAME = "sprint4-demo-vpc"
SUBNET_NAME = "sprint4-demo-subnet"


def local_url(name):
    value = os.environ.get(name, "")
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError(f"Set {name} to an http://localhost:<port> URL for this local demo.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError(f"{name} must be a plain local base URL.")
    return value.rstrip("/")


def region():
    value = os.environ.get("AWS_DEFAULT_REGION", "")
    if value != "us-east-1":
        raise ValueError("Set AWS_DEFAULT_REGION=us-east-1 to match the LO1 policy.")
    return value


def aws(service, operation, *arguments):
    command = ["aws", service, operation, *arguments, "--endpoint-url", local_url("FLOCI_ENDPOINT"),
               "--region", region(), "--output", "json", "--no-cli-pager"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"AWS CLI failed: {error.stderr.strip()}") from None
    return json.loads(result.stdout) if result.stdout.strip() else {}


def write_json(name, value):
    folder = ROOT / ".generated"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def execution_role():
    return aws("iam", "get-role", "--role-name", "application-execution-role")["Role"]["Arn"]
