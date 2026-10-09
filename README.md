# Sprint 4: Work with Managed Messaging and Database Services

## Demo 1: Decouple an Application with a Managed Queue and Topic

**Learning outcome:** Use a managed queue and a notification topic to pass work and broadcast events between application components.

The Sprint 2 application is extended so `/chat` also sends each message to a queue and publishes it to a topic. You will see a queue hold messages while its consumer is away, see a duplicate delivery, and see one published event reach two subscribers.

## Before starting

- Ubuntu with Docker Engine, Docker Compose plugin, Python 3.12, AWS CLI v2, Git and curl. Docker works without `sudo`. The AWS CLI profile `floci` is configured (`test`, `test`, `us-east-1`, `json`).
- This project is self-contained: it has its own `docker-compose.yml`, its own `data` folder (created on first start) and the supplied role files `trust-policy.json` and `execution-policy.json`. Nothing from earlier sprints is needed.
- Only one Floci can run at a time (port 4566). If an earlier sprint's Floci is running, stop it from that project's folder with `docker compose down`.
- Open **two terminals** in this project's root. Use **Terminal 1** unless a step says Terminal 2. If you open a new terminal, repeat Step 2's variables.

## 1. Start Floci

```bash
docker compose pull
docker compose up -d
docker compose ps
curl -fsS http://localhost:4566/_floci/health | head -c 60
```

**Why:** Starts Floci 2.2.0 from this project's compose file, with Docker access so ECS tasks and databases run as real containers.

**Expected:** Floci is running and the health JSON shows `"version":"2.2.0"`. Retry the `curl` after a few seconds if Floci is still starting.

## 2. Create the execution role and set variables (Terminal 1)

```bash
export FLOCI_ENDPOINT='http://localhost:4566' AWS_DEFAULT_REGION='us-east-1' AWS_PROFILE='floci' AWS_PAGER='' APP_BASE_URL='http://localhost:8080'
unset GITHUB_SHA GITHUB_ENV GITHUB_STEP_SUMMARY
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --endpoint-url "$FLOCI_ENDPOINT")
echo "$ACCOUNT_ID"
aws iam create-role --role-name application-execution-role --assume-role-policy-document file://trust-policy.json --endpoint-url "$FLOCI_ENDPOINT"
aws iam put-role-policy --role-name application-execution-role --policy-name application-pull-and-logs --policy-document file://execution-policy.json --endpoint-url "$FLOCI_ENDPOINT"
```

**Why:** The deployment scripts use this role to pull the image and write logs. The supplied policy files already contain Floci's account ID.

**Expected:** the account ID is `000000000000`, and the role is created with the ECS trust policy.

## 3. Install dependencies and run tests

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

**Expected:** installation succeeds; all tests pass and the output ends with `OK`.

## 4. Publish and deploy the new image

```bash
git add . && git commit -m 'Add queue and topic support'
DEMO_SHA=$(git rev-parse HEAD)
.venv/bin/python -m scripts.prepare_local
.venv/bin/python -m scripts.publish
export IMAGE_URI="$(.venv/bin/python -c 'import json; print(json.load(open("local-config.json"))["repository_uri"])'):$DEMO_SHA"
export FLOCI_SUBNET_ID="$(.venv/bin/python -c 'import json; print(json.load(open("local-config.json"))["subnet_id"])')"
.venv/bin/python -m scripts.deploy
```

**Why:** The application code changed, so a new image is built once. Later steps only change settings and redeploy this same image.

**Expected:** `ecs_health` is `HEALTHY` and `health.version` matches `$DEMO_SHA`. `prepare_local` creates the registry repository, log group and cluster, and `deploy` creates the service.

## 5. Create the queue

```bash
aws sqs create-queue --queue-name application-events --endpoint-url "$FLOCI_ENDPOINT"
QUEUE_URL=$(aws sqs get-queue-url --queue-name application-events --query QueueUrl --output text --endpoint-url "$FLOCI_ENDPOINT")
echo "$QUEUE_URL"
```

**Expected:** a queue URL ending in `/000000000000/application-events`. Floci returns `localhost` in this URL, so the application looks the queue up by name instead.

## 6. Start the consumer (Terminal 2)

```bash
export FLOCI_ENDPOINT='http://localhost:4566' AWS_DEFAULT_REGION='us-east-1' AWS_PROFILE='floci'
.venv/bin/python worker.py --queue-name application-events
```

**Expected:** `Waiting for messages on application-events.` Leave it running.

## 7. Connect the application to the queue (Terminal 1)

```bash
export QUEUE_NAME='application-events'
.venv/bin/python -m scripts.deploy
curl -fsS http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"Order 1001 placed"}'
```

**Why:** `deploy` passes `QUEUE_NAME` to the container. The application now sends every `/chat` message to the queue.

**Expected:** `ecs_health` is `HEALTHY`; the reply is `{"reply":"Application received: Order 1001 placed"}`. Terminal 2 prints `RECEIVED <id>: Hello` (sent by `deploy`) and `RECEIVED <id>: Order 1001 placed`.

## 8. See the queue hold messages while the consumer is away

In **Terminal 2**, press **Ctrl+C** to stop the worker. Then in **Terminal 1**:

```bash
for n in 1 2 3; do curl -fsS http://localhost:8080/chat -H 'Content-Type: application/json' -d "{\"message\":\"Order 200$n placed\"}"; done
aws sqs get-queue-attributes --queue-url "$QUEUE_URL" --attribute-names ApproximateNumberOfMessages --endpoint-url "$FLOCI_ENDPOINT"
```

**Why:** The application answers immediately even with no consumer running. The messages wait in the queue.

**Expected:** three replies and `ApproximateNumberOfMessages` of `3`. Restart the worker in Terminal 2 (Step 6 command): it prints all three, and the count returns to `0`.

## 9. See a duplicate delivery

In **Terminal 2**, stop the worker and restart it without deleting messages:

```bash
.venv/bin/python worker.py --queue-name application-events --no-delete --visibility-timeout 5
```

In **Terminal 1**:

```bash
curl -fsS http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"Order 3001 placed"}'
```

**Why:** A message stays in the queue until the consumer deletes it. If it is not deleted, the queue delivers it again.

**Expected:** Terminal 2 prints `RECEIVED` once, then `DUPLICATE ignored` with the same id every few seconds. The consumer recognises the repeated `message_id` and does not process it twice.

Stop the worker (**Ctrl+C**) and restart it normally (Step 6 command) to delete the message.

## 10. Create a topic with two subscribers (Terminal 1)

```bash
aws sns create-topic --name application-topic --endpoint-url "$FLOCI_ENDPOINT"
for q in email-subscriber audit-subscriber; do
  aws sqs create-queue --queue-name "$q" --endpoint-url "$FLOCI_ENDPOINT"
  aws sns subscribe --topic-arn "arn:aws:sns:us-east-1:$ACCOUNT_ID:application-topic" --protocol sqs \
    --notification-endpoint "arn:aws:sqs:us-east-1:$ACCOUNT_ID:$q" --endpoint-url "$FLOCI_ENDPOINT"
done
aws sns list-subscriptions-by-topic --topic-arn "arn:aws:sns:us-east-1:$ACCOUNT_ID:application-topic" --query 'Subscriptions[].Endpoint' --endpoint-url "$FLOCI_ENDPOINT"
```

**Why:** A queue delivers each message to one consumer. A topic delivers each event to every subscriber.

**Expected:** the list shows both subscriber queue ARNs. (On real AWS each queue also needs a policy allowing the topic to send to it; the local emulator does not require this.)

## 11. Connect the application to the topic and broadcast an event

```bash
export TOPIC_ARN="arn:aws:sns:us-east-1:$ACCOUNT_ID:application-topic"
.venv/bin/python -m scripts.deploy
curl -fsS http://localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"Order 4001 placed"}'
for q in email-subscriber audit-subscriber; do
  aws sqs receive-message --queue-url "$FLOCI_ENDPOINT/$ACCOUNT_ID/$q" --query 'Messages[0].Body' --output text --endpoint-url "$FLOCI_ENDPOINT"
done
```

**Expected:** `ecs_health` is `HEALTHY`. Both subscriber queues show a notification containing `Order 4001 placed` (a JSON wrapper with `TopicArn` and `Message`). The worker in Terminal 2 also prints `RECEIVED ... Order 4001 placed` from `application-events`: one request, one queue consumer, two topic subscribers.

## Completion checklist

- A `/chat` message reached the worker through the queue.
- Messages waited in the queue while the worker was stopped, then were all processed.
- A duplicate delivery occurred and was ignored by `message_id`.
- One event published to the topic arrived in both subscriber queues.

Keep Floci, the queue, the topic and the deployed application running for Demo 2. Stop everything with `docker compose down` (the `data` folder keeps your resources).

## Troubleshooting — only when needed

| Problem | Action |
|---|---|
| `deploy` fails with a `/chat` error (502) | The queue or topic does not exist yet, or its name is wrong. Create it first, then check `echo "$QUEUE_NAME" "$TOPIC_ARN"`. |
| Worker prints `QueueDoesNotExist` | Check the name with `aws sqs list-queues --endpoint-url "$FLOCI_ENDPOINT"`. |
| Worker cannot find credentials | Repeat Terminal 2's `export` line. |
| Messages sent but worker prints nothing | `QUEUE_NAME` was lost (new terminal) or `deploy` was not rerun. Export it and redeploy. |
| Port 4566 in use | Another Floci is running. Stop it with `docker compose down` in its project folder. |
| `create-role` says the role exists | It was kept in `data` from an earlier run. Continue. |
| Role missing after a restart | The `data` folder was deleted. Repeat Step 2. |
| Port 8080 in use | Stop any other container or app using it, then redeploy. |
| Docker Hub pull times out | Run `docker pull python:3.12-slim` on a stable connection before the session. |

Read the application's log if `/chat` fails:

```bash
aws logs filter-log-events --log-group-name /ecs/application-service --endpoint-url "$FLOCI_ENDPOINT"
```