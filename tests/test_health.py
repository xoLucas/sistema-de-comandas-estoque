import unittest

from fastapi.responses import JSONResponse

from app.main import health_live, health_ready


class _ReadyDatabase:
    async def scalar(self, _statement):
        return 1


class _UnavailableDatabase:
    async def scalar(self, _statement):
        raise RuntimeError("database unavailable")


class HealthEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_liveness_is_public_and_does_not_require_database(self) -> None:
        self.assertEqual(await health_live(), {"status": "ok"})

    async def test_readiness_reports_database_state(self) -> None:
        self.assertEqual(
            await health_ready(_ReadyDatabase()),
            {"status": "ready"},
        )
        unavailable = await health_ready(_UnavailableDatabase())
        self.assertIsInstance(unavailable, JSONResponse)
        self.assertEqual(unavailable.status_code, 503)


if __name__ == "__main__":
    unittest.main()
