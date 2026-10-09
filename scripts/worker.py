"""Consumes the application queue from the host and prints each message.
Reads from a queue directly or from a queue subscribed to a topic.
Ignores a message whose message_id was already seen, because delivery is at-least-once.
"""

import argparse
import json
import os

import boto3


def parse(body):
    """Returns the application event, unwrapping a topic notification if present."""
    data = json.loads(body)
    if isinstance(data, dict) and "TopicArn" in data and "Message" in data:
        try:
            return json.loads(data["Message"])
        except ValueError:
            return {"message_id": data.get("MessageId"), "message": data["Message"]}
    return data


def main():
    parser = argparse.ArgumentParser(description="Print messages from a queue.")
    parser.add_argument("--queue-name", default=os.getenv("QUEUE_NAME"), help="queue to read")
    parser.add_argument("--no-delete", action="store_true",
                        help="do not delete messages, so they are delivered again")
    parser.add_argument("--visibility-timeout", type=int, default=10,
                        help="seconds before an undeleted message is delivered again")
    args = parser.parse_args()
    if not args.queue_name:
        raise SystemExit("Provide --queue-name or set QUEUE_NAME.")

    sqs = boto3.client("sqs", endpoint_url=os.getenv("FLOCI_ENDPOINT", "http://localhost:4566"),
                       region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    url = sqs.get_queue_url(QueueName=args.queue_name)["QueueUrl"]
    seen = set()
    print(f"Waiting for messages on {args.queue_name}. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            response = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1, WaitTimeSeconds=5,
                                           VisibilityTimeout=args.visibility_timeout)
            for item in response.get("Messages", []):
                event = parse(item["Body"])
                message_id = event.get("message_id")
                if message_id in seen:
                    print(f"DUPLICATE ignored: {message_id}", flush=True)
                else:
                    seen.add(message_id)
                    print(f"RECEIVED {message_id}: {event.get('message')}", flush=True)
                if not args.no_delete:
                    sqs.delete_message(QueueUrl=url, ReceiptHandle=item["ReceiptHandle"])
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
