import json
import sys


class VaultError(Exception):
    pass


class SystemVault:
    """Choose only system credential stores. Never fall back to file/plaintext storage."""

    def __init__(self, service):
        self.service = service
        try:
            if sys.platform == "win32":
                from keyring.backends.Windows import WinVaultKeyring

                self.backend = WinVaultKeyring()
            elif sys.platform == "darwin":
                from keyring.backends.macOS import Keyring

                self.backend = Keyring()
            else:
                from keyring.backends.SecretService import Keyring

                self.backend = Keyring()
            if self.backend.priority <= 0:
                raise VaultError
        except Exception:
            raise VaultError("Системное хранилище учётных данных недоступно.") from None

    def get(self, name):
        try:
            value = self.backend.get_password(self.service, name)
            return json.loads(value) if value else None
        except Exception:
            raise VaultError("Не удалось прочитать системное хранилище.") from None

    def put(self, name, value):
        try:
            self.backend.set_password(self.service, name, json.dumps(value))
        except Exception:
            raise VaultError("Не удалось сохранить авторизацию в системном хранилище.") from None

    def remove(self, name):
        try:
            if self.backend.get_password(self.service, name) is not None:
                self.backend.delete_password(self.service, name)
        except Exception:
            raise VaultError("Не удалось удалить запись системного хранилища.") from None
