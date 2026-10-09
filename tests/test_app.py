import os
import unittest
from unittest.mock import patch

from app import app


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health_identifies_deployed_version(self):
        with patch.dict(os.environ, {"APP_VERSION": "a" * 40}):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok", "version": "a" * 40})

    def test_chat_returns_expected_response(self):
        response = self.client.post("/chat", json={"message": " Hello "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"reply": "Application received: Hello"})

    def test_invalid_messages_are_rejected(self):
        for body in [{}, {"message": " "}, {"message": 12}, [], None]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/chat", json=body).status_code, 400)

    def test_long_message_is_rejected(self):
        self.assertEqual(self.client.post("/chat", json={"message": "x" * 1001}).status_code, 400)

    def test_malformed_json_is_rejected(self):
        response = self.client.post("/chat", data="{broken", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_chat_requires_post(self):
        self.assertEqual(self.client.get("/chat").status_code, 405)


if __name__ == "__main__":
    unittest.main()
