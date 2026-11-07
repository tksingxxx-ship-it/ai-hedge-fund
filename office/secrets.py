"""Encrypted credential file.

The file is written mode 0600. The key is derived from OFFICE_MASTER_KEY.
There is no built-in key. When the variable is missing the office refuses
to store a credential rather than writing plaintext.
"""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from office.redact import SECRET_ENV_VARS

_AAD = b"aihf-office-credential-v1"
_MIN_MASTER = 16


class MasterKeyMissing(RuntimeError):
    pass


def master_configured() -> bool:
    value = os.environ.get("OFFICE_MASTER_KEY") or ""
    return len(value) >= _MIN_MASTER


def _derive(salt: bytes) -> bytes:
    raw = os.environ.get("OFFICE_MASTER_KEY") or ""
    if len(raw) < _MIN_MASTER:
        raise MasterKeyMissing(
            "OFFICE_MASTER_KEY is not set to at least 16 characters. "
            "The office will not store credentials without it."
        )
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    return kdf.derive(raw.encode())


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("secrets file is not an object")
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def store_secret(path: Path, env_var: str, value: str) -> None:
    if env_var not in SECRET_ENV_VARS:
        raise ValueError(f"{env_var} is not a credential the office is allowed to store")
    if not value or not value.strip():
        raise ValueError("credential is empty")
    salt = os.urandom(16)
    key = _derive(salt)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, value.encode(), _AAD)
    blob = {
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ciphertext).decode(),
    }
    data = _read(path)
    data[env_var] = blob
    _write(path, data)
    os.environ[env_var] = value


def delete_secret(path: Path, env_var: str) -> None:
    data = _read(path)
    data.pop(env_var, None)
    _write(path, data)
    os.environ.pop(env_var, None)


def stored_names(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return sorted(_read(path))
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def load_into_environ(path: Path) -> list[str]:
    """Decrypt stored credentials into the process environment.

    A variable that is already set is left alone, matching the engine rule
    that the shell wins over a file.
    """
    if not path.exists() or not master_configured():
        return []
    loaded = []
    for name, blob in _read(path).items():
        if name not in SECRET_ENV_VARS or os.environ.get(name):
            continue
        try:
            salt = base64.b64decode(blob["salt"])
            nonce = base64.b64decode(blob["nonce"])
            ct = base64.b64decode(blob["ct"])
            plain = AESGCM(_derive(salt)).decrypt(nonce, ct, _AAD).decode()
        except Exception:
            continue
        os.environ[name] = plain
        loaded.append(name)
    return loaded
