import os
import unittest
from unittest.mock import patch

from scripts.deploy import render_task
from scripts.local_cloud import local_url


class DeploymentConfigurationTests(unittest.TestCase):
    def test_role_image_and_healthcheck_survive_rendering(self):
        sha = "b" * 40
        image = "localhost:4566/000000000000/us-east-1/application-service:" + sha
        role = "arn:aws:iam::000000000000:role/application-execution-role"
        task = render_task(image, role, sha, "us-east-1")
        self.assertEqual(task["executionRoleArn"], role)
        self.assertNotIn("taskRoleArn", task)
        container = task["containerDefinitions"][0]
        self.assertEqual(container["image"], image)
        self.assertEqual(container["environment"][0]["value"], sha)
        self.assertIn("/health", container["healthCheck"]["command"][-1])
        self.assertEqual(container["logConfiguration"]["options"]["awslogs-group"], "/ecs/application-service")

    def test_local_demo_rejects_remote_endpoints(self):
        for url in ["https://ecs.us-east-1.amazonaws.com", "http://example.com:4566", "", "http://user:pass@localhost:4566"]:
            with self.subTest(url=url), patch.dict(os.environ, {"FLOCI_ENDPOINT": url}):
                with self.assertRaises(ValueError):
                    local_url("FLOCI_ENDPOINT")


if __name__ == "__main__":
    unittest.main()
