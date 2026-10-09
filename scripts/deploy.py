"""Deploys the published image through Floci's ECS service.
Registers the task definition and waits for a healthy running task.
Checks /health and /chat, then saves deployment evidence.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
APP_SETTINGS = ("QUEUE_NAME", "TOPIC_ARN", "DATABASE_URL")

from scripts.local_cloud import CLUSTER, ROOT, SERVICE, aws, execution_role, local_url, region, write_json


def render_task(image, role, sha, aws_region):
    task = json.loads((ROOT / "ecs/task-definition.template.json").read_text(encoding="utf-8"))
    task["executionRoleArn"] = role
    container = task["containerDefinitions"][0]
    container["image"] = image
    container["environment"][0]["value"] = sha
    container["logConfiguration"]["options"]["awslogs-region"] = aws_region
    for name in APP_SETTINGS:
        value = os.environ.get(name)
        if value:
            container["environment"].append({"name": name, "value": value})
    return task


def request_json(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP status {response.status}")
        return json.load(response)


def wait_until(check, description, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(3)
    raise RuntimeError(f"Timed out waiting for {description}; inspect stopped tasks and Floci logs.")


def running_tasks():
    return aws("ecs", "list-tasks", "--cluster", CLUSTER, "--service-name", SERVICE)["taskArns"]


def main():
    image = os.environ.get("IMAGE_URI", "")
    sha = image.rsplit(":", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Set IMAGE_URI to the registry image with its full Git SHA tag.")
    subnet = os.environ.get("FLOCI_SUBNET_ID", "")
    if not subnet.startswith("subnet-"):
        raise ValueError("Set FLOCI_SUBNET_ID using the preparation script output.")
    base_url = local_url("APP_BASE_URL")
    task = render_task(image, execution_role(), sha, region())
    path = write_json("task-definition.json", task)
    task_arn = aws("ecs", "register-task-definition", "--cli-input-json", f"file://{path.as_posix()}")["taskDefinition"]["taskDefinitionArn"]
    description = aws("ecs", "describe-services", "--cluster", CLUSTER, "--services", SERVICE)
    existing = next((service for service in description.get("services", []) if service.get("status") == "ACTIVE"), None)
    if existing:
        # The local fixed port cannot serve two replacement tasks at once.
        print("Stopping the previous lab task to release port 8080.", flush=True)
        old_arns = running_tasks()
        aws("ecs", "update-service", "--cluster", CLUSTER, "--service", SERVICE, "--desired-count", "0")
        def previous_stopped():
            if not old_arns:
                return True
            old = aws("ecs", "describe-tasks", "--cluster", CLUSTER, "--tasks", *old_arns)
            return not old.get("failures") and all(item["lastStatus"] == "STOPPED" for item in old["tasks"])
        wait_until(previous_stopped, "previous task to stop")
        aws("ecs", "update-service", "--cluster", CLUSTER, "--service", SERVICE,
            "--task-definition", task_arn, "--desired-count", "1")
    else:
        service_input = {
            "cluster": CLUSTER, "serviceName": SERVICE, "taskDefinition": task_arn,
            "desiredCount": 1, "launchType": "FARGATE",
            "networkConfiguration": {"awsvpcConfiguration": {"subnets": [subnet], "assignPublicIp": "DISABLED"}},
            "deploymentConfiguration": {"minimumHealthyPercent": 0, "maximumPercent": 100}
        }
        path = write_json("service.json", service_input)
        aws("ecs", "create-service", "--cli-input-json", f"file://{path.as_posix()}")

    def ready_task():
        arns = running_tasks()
        if not arns:
            return None
        tasks = aws("ecs", "describe-tasks", "--cluster", CLUSTER, "--tasks", *arns)["tasks"]
        for candidate in tasks:
            containers = candidate.get("containers", [])
            if (candidate.get("lastStatus") == "RUNNING" and candidate.get("taskDefinitionArn") == task_arn
                    and containers and containers[0].get("image") == image
                    and candidate.get("healthStatus") == "HEALTHY"):
                return candidate
        return None

    deployed = wait_until(ready_task, "the new ECS task to become healthy")
    health = request_json(base_url + "/health")
    if health != {"status": "ok", "version": sha}:
        raise RuntimeError("/health did not identify the new commit; an old application may be answering.")
    chat = request_json(base_url + "/chat", {"message": "Hello"})
    if chat != {"reply": "Application received: Hello"}:
        raise RuntimeError("/chat returned an unexpected response.")
    evidence = {"image": image, "task_definition": task_arn, "task_arn": deployed["taskArn"],
                "health": health, "chat": chat, "ecs_health": deployed["healthStatus"]}
    write_json("deployment-evidence.json", evidence)
    print(json.dumps(evidence, indent=2))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(f"## Local deployment verified\n\nImage: `{image}`\n\nTask: `{deployed['taskArn']}`\n\n")
            stream.write("ECS task healthy; /health identifies this commit; /chat returns the expected reply.\n")


if __name__ == "__main__":
    main()
