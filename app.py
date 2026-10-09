"""Provides a small application for the managed-services demo.
The /health endpoint reports application status and the deployed Git SHA.
The /chat endpoint returns a fixed reply and, when configured, saves the message
to a database, sends it to a queue and publishes an event to a topic.
The /messages endpoint lists the saved messages.
"""

import json
import logging
import os
import uuid
from urllib.parse import urlparse

from flask import Flask, jsonify, request
from waitress import serve

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def aws_client(service):
    """Creates a client that talks to the endpoint named in AWS_ENDPOINT_URL."""
    import boto3
    return boto3.client(service, endpoint_url=os.getenv("AWS_ENDPOINT_URL") or None,
                        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


def queue_url(sqs, name):
    """Resolves a queue name to a URL this container can reach.

    Floci reports queue URLs that start with localhost, which is the container
    itself from inside ECS, so the host part is replaced with the endpoint.
    """
    url = sqs.get_queue_url(QueueName=name)["QueueUrl"]
    endpoint = os.getenv("AWS_ENDPOINT_URL")
    return endpoint.rstrip("/") + urlparse(url).path if endpoint else url


def database():
    import psycopg2
    connection = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=5)
    with connection, connection.cursor() as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS messages ("
                       "id uuid PRIMARY KEY, body text NOT NULL, "
                       "created_at timestamptz NOT NULL DEFAULT now())")
    return connection


def save_message(message_id, text):
    connection = database()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO messages (id, body) VALUES (%s, %s)", (message_id, text))
    finally:
        connection.close()


def send_to_queue(event):
    sqs = aws_client("sqs")
    sqs.send_message(QueueUrl=queue_url(sqs, os.environ["QUEUE_NAME"]), MessageBody=event)


def publish_event(event):
    aws_client("sns").publish(TopicArn=os.environ["TOPIC_ARN"], Message=event)


@app.get("/health")
def health():
    return jsonify(status="ok", version=os.getenv("APP_VERSION", "local"))


@app.post("/chat")
def chat():
    body = request.get_json(silent=True)
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, str) or not message.strip():
        return jsonify(error="Provide a non-empty message string."), 400
    if len(message) > 1000:
        return jsonify(error="Message must be at most 1000 characters."), 400
    message = message.strip()
    message_id = str(uuid.uuid4())
    event = json.dumps({"message_id": message_id, "message": message})
    try:
        if os.getenv("DATABASE_URL"):
            save_message(message_id, message)
        if os.getenv("QUEUE_NAME"):
            send_to_queue(event)
        if os.getenv("TOPIC_ARN"):
            publish_event(event)
    except Exception:
        app.logger.exception("A downstream service call failed")
        return jsonify(error="A downstream service call failed."), 502
    app.logger.info("Chat request handled")
    return jsonify(reply=f"Application received: {message}")


@app.get("/messages")
def messages():
    if not os.getenv("DATABASE_URL"):
        return jsonify(error="DATABASE_URL is not configured."), 404
    try:
        connection = database()
        try:
            with connection, connection.cursor() as cursor:
                cursor.execute("SELECT id, body, created_at FROM messages ORDER BY created_at DESC LIMIT 20")
                rows = cursor.fetchall()
        finally:
            connection.close()
    except Exception:
        app.logger.exception("Could not read messages")
        return jsonify(error="Could not read messages."), 502
    return jsonify(messages=[{"id": str(row[0]), "body": row[1], "created_at": row[2].isoformat()}
                             for row in rows])


if __name__ == "__main__":
    app.logger.info("Application starting on port 8080")
    serve(app, host="0.0.0.0", port=8080)
