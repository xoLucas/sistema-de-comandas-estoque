import unittest
from types import SimpleNamespace

from app.routers.auth_deps import can_manage_notifications


class NotificationPermissionTests(unittest.TestCase):
    @staticmethod
    def _user(role: str):
        return SimpleNamespace(role=role)

    def test_gerente_caixa_e_garcom_podem_gerenciar(self) -> None:
        for role in ("gerente", "caixa", "garcom"):
            self.assertTrue(can_manage_notifications(self._user(role)), role)

    def test_estoquista_nao_pode_gerenciar(self) -> None:
        self.assertFalse(can_manage_notifications(self._user("estoquista")))


if __name__ == "__main__":
    unittest.main()
