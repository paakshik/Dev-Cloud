import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://invalid:[REDACTED]@127.0.0.1:1/test")
os.environ["REDIS_URL"] = ""
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"

from fastapi.testclient import TestClient
from main import ALLOWED_ORIGINS, app


class CorsTests(unittest.TestCase):
    def test_production_vercel_frontend_origin_is_allowed(self):
        origin = "https://dev-cloud-frontend-ltfv.vercel.app"
        self.assertIn(origin, ALLOWED_ORIGINS)
        with TestClient(app) as client:
            response = client.options(
                "/api/v1/stats",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)


if __name__ == "__main__":
    unittest.main()
