"""
ndi.cloud.profile - Singleton manager for NDI Cloud user profiles.

This is the Python port of MATLAB ``ndi.cloud.profile``.  It keeps a
list of NDI Cloud login profiles for the current OS user.  Each profile
carries a ``Nickname``, an ``Email``, an auto-generated ``UID``, and a
``Stage`` (``'prod'`` or ``'dev'``).  Passwords are not stored in the
profile JSON; instead each profile points at a secret keyed by
``'NDI Cloud ' + UID`` in a pluggable backend.

Backends, chosen automatically on first use:

    keyring  -- the OS-native credential store via the ``keyring``
                package.  Preferred when available.  Equivalent to
                MATLAB's "vault" backend.
    aes      -- AES-128/CBC encrypted file in the user's prefdir,
                used when ``keyring`` is not installed.  The key is
                derived from SHA-256([hostname username 'NDI Cloud'])
                so the file is reproducible only on the machine that
                wrote it.
    memory   -- in-memory dict.  Reserved for tests; use
                ``ndi.cloud.profile.use_backend('memory')`` to opt in.

Current vs default profile
--------------------------
The class distinguishes between two notions of "selected":

    current_uid - the active profile for THIS Python process.
                  Held in memory only; never persisted.
    default_uid - the user's preferred profile, persisted to the JSON
                  file.  At construction the singleton copies a valid
                  ``default_uid`` into ``current_uid``.

MATLAB equivalent: +cloud/profile.m
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import os
import secrets
import socket
import tempfile
import uuid
from base64 import b64decode, b64encode
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


_BackendName = Literal["keyring", "aes", "memory"]
_SECRET_KEY_PREFIX = "NDI Cloud "


# ---------------------------------------------------------------------------
# Profile entry
# ---------------------------------------------------------------------------


@dataclass
class ProfileEntry:
    """One entry in the profile list."""

    UID: str = ""
    Nickname: str = ""
    Email: str = ""
    Stage: str = "prod"
    PasswordSecret: str = ""


def _prefdir() -> Path:
    """Return the directory where profile state is persisted.

    Honours ``NDI_PREFDIR`` if set, otherwise uses
    ``~/.ndi`` (created if absent), falling back to the system temp
    directory if the home dir is unwritable.
    """
    override = os.environ.get("NDI_PREFDIR", "")
    if override:
        return Path(override)
    try:
        d = Path.home() / ".ndi"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return Path(tempfile.gettempdir())


# ---------------------------------------------------------------------------
# AES helpers (used when no OS keyring is available)
# ---------------------------------------------------------------------------


def _aes_key_bytes() -> bytes:
    try:
        host = socket.gethostname()
    except OSError:  # pragma: no cover - extreme defensive
        host = "localhost"
    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - extreme defensive
        user = "unknown"
    seed = f"{host} {user} NDI Cloud".encode("utf-8")
    return hashlib.sha256(seed).digest()[:16]


def _aes_encrypt(value: str) -> dict[str, str]:
    """Encrypt *value* with AES-128/CBC and return iv+ciphertext (base64)."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = _aes_key_bytes()
    iv = secrets.token_bytes(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(value.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(padded) + enc.finalize()
    return {
        "iv": b64encode(iv).decode("ascii"),
        "ciphertext": b64encode(ct).decode("ascii"),
    }


def _aes_decrypt(entry: dict) -> str:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = _aes_key_bytes()
    iv = b64decode(entry["iv"])
    ct = b64decode(entry["ciphertext"])
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    return plain.decode("utf-8")


def _read_secrets_file(filename: Path) -> dict:
    if not filename.is_file():
        return {}
    try:
        return json.loads(filename.read_text())
    except (ValueError, OSError):
        return {}


def _write_secrets_file(filename: Path, payload: dict) -> None:
    filename.write_text(json.dumps(payload, indent=2))


def _safe_field(name: str) -> str:
    """Map a secret key to a JSON-safe field name."""
    return name.replace(" ", "_").replace(":", "_")


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------


def _detect_backend() -> _BackendName:
    try:
        import keyring  # noqa: F401
    except ImportError:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher  # noqa: F401
        except ImportError:
            logger.warning(
                "Neither 'keyring' nor 'cryptography' is installed; "
                "ndi.cloud.profile will fall back to the in-memory backend "
                "which does NOT persist secrets to disk."
            )
            return "memory"
        return "aes"
    return "keyring"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


@dataclass
class _ProfileSingleton:
    profiles: list[ProfileEntry] = field(default_factory=list)
    current_uid: str = ""
    default_uid: str = ""
    backend: _BackendName = "memory"
    _memory_store: dict[str, str] = field(default_factory=dict)

    # ------------- filesystem paths -------------

    @property
    def filename(self) -> Path:
        return _prefdir() / "NDI_Cloud_Profiles.json"

    @property
    def secrets_filename(self) -> Path:
        return _prefdir() / "NDI_Cloud_Secrets.json"

    # ------------- disk I/O -------------

    def _load_from_disk(self) -> None:
        if not self.filename.is_file():
            return
        try:
            data = json.loads(self.filename.read_text())
        except (ValueError, OSError) as exc:
            logger.warning("Could not load cloud profiles from %s: %s", self.filename, exc)
            return
        raw = data.get("Profiles") or []
        self.profiles = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            entry = ProfileEntry(
                UID=str(item.get("UID", "")),
                Nickname=str(item.get("Nickname", "")),
                Email=str(item.get("Email", "")),
                Stage=str(item.get("Stage", "prod")),
                PasswordSecret=str(item.get("PasswordSecret", "")),
            )
            if not entry.PasswordSecret and entry.UID:
                entry.PasswordSecret = _SECRET_KEY_PREFIX + entry.UID
            self.profiles.append(entry)
        self.default_uid = str(data.get("DefaultUID", ""))

    def _save_to_disk(self) -> None:
        payload = {
            "Profiles": [asdict(p) for p in self.profiles],
            "DefaultUID": self.default_uid,
        }
        try:
            self.filename.write_text(json.dumps(payload, indent=2))
        except OSError as exc:
            logger.warning("Could not save cloud profiles to %s: %s", self.filename, exc)

    def _adopt_default_as_current(self) -> None:
        if not self.default_uid or not self.profiles:
            return
        if any(p.UID == self.default_uid for p in self.profiles):
            self.current_uid = self.default_uid

    # ------------- lookup -------------

    def _find_index(self, uid: str) -> int:
        for i, p in enumerate(self.profiles):
            if p.UID == uid:
                return i
        raise KeyError(f'Unknown profile UID "{uid}".')

    # ------------- secrets backend -------------

    def _set_secret(self, key: str, value: str) -> None:
        if self.backend == "keyring":
            import keyring

            keyring.set_password("ndi-cloud", key, value)
        elif self.backend == "aes":
            store = _read_secrets_file(self.secrets_filename)
            store[_safe_field(key)] = _aes_encrypt(value)
            _write_secrets_file(self.secrets_filename, store)
        else:  # memory
            self._memory_store[key] = value

    def _get_secret(self, key: str) -> str:
        if self.backend == "keyring":
            import keyring

            value = keyring.get_password("ndi-cloud", key)
            if value is None:
                raise KeyError(f'No secret stored for "{key}".')
            return value
        if self.backend == "aes":
            store = _read_secrets_file(self.secrets_filename)
            entry = store.get(_safe_field(key))
            if entry is None:
                raise KeyError(f'No secret stored for "{key}".')
            return _aes_decrypt(entry)
        if key not in self._memory_store:
            raise KeyError(f'No secret stored for "{key}".')
        return self._memory_store[key]

    def _remove_secret(self, key: str) -> None:
        if self.backend == "keyring":
            import keyring

            try:
                keyring.delete_password("ndi-cloud", key)
            except Exception:  # noqa: BLE001 - keyring raises a family of errors
                pass
        elif self.backend == "aes":
            store = _read_secrets_file(self.secrets_filename)
            store.pop(_safe_field(key), None)
            _write_secrets_file(self.secrets_filename, store)
        else:
            self._memory_store.pop(key, None)


_singleton: _ProfileSingleton | None = None


def _get_singleton() -> _ProfileSingleton:
    global _singleton
    if _singleton is None:
        obj = _ProfileSingleton(backend=_detect_backend())
        obj._load_from_disk()
        obj._adopt_default_as_current()
        _singleton = obj
    return _singleton


# ---------------------------------------------------------------------------
# Public API (mirrors MATLAB static methods)
# ---------------------------------------------------------------------------


def list_profiles() -> list[ProfileEntry]:
    """Return a shallow copy of the profile list."""
    return list(_get_singleton().profiles)


def get(uid: str) -> ProfileEntry:
    """Return the profile entry for *uid*."""
    obj = _get_singleton()
    return obj.profiles[obj._find_index(uid)]


def add(nickname: str, email: str, password: str) -> str:
    """Create a new profile, store its password, and return the new UID."""
    obj = _get_singleton()
    uid = uuid.uuid4().hex
    secret_key = _SECRET_KEY_PREFIX + uid
    entry = ProfileEntry(
        UID=uid,
        Nickname=nickname,
        Email=email,
        Stage="prod",
        PasswordSecret=secret_key,
    )
    obj.profiles.append(entry)
    obj._set_secret(secret_key, password)
    obj._save_to_disk()
    return uid


def remove(uid: str) -> None:
    """Delete a profile and its stored secret."""
    obj = _get_singleton()
    idx = obj._find_index(uid)
    secret_key = obj.profiles[idx].PasswordSecret
    obj._remove_secret(secret_key)
    del obj.profiles[idx]
    if obj.current_uid == uid:
        obj.current_uid = ""
    if obj.default_uid == uid:
        obj.default_uid = ""
    obj._save_to_disk()


def get_current() -> ProfileEntry | None:
    """Return the active profile for this session, or None."""
    obj = _get_singleton()
    if not obj.current_uid:
        return None
    try:
        return get(obj.current_uid)
    except KeyError:
        return None


def set_current(uid: str) -> None:
    """Set the current profile for this session (in memory only)."""
    obj = _get_singleton()
    obj._find_index(uid)  # validates existence
    obj.current_uid = uid


def get_default() -> ProfileEntry | None:
    """Return the persisted default profile, or None."""
    obj = _get_singleton()
    if not obj.default_uid:
        return None
    try:
        return get(obj.default_uid)
    except KeyError:
        return None


def set_default(uid: str) -> None:
    """Persist *uid* as the default profile."""
    obj = _get_singleton()
    obj._find_index(uid)
    obj.default_uid = uid
    obj._save_to_disk()


def clear_default() -> None:
    """Forget any persisted default."""
    obj = _get_singleton()
    obj.default_uid = ""
    obj._save_to_disk()


def get_password(uid: str) -> str:
    """Retrieve the stored password for *uid*."""
    obj = _get_singleton()
    idx = obj._find_index(uid)
    return obj._get_secret(obj.profiles[idx].PasswordSecret)


def set_password(uid: str, password: str) -> None:
    """Update a profile's stored password."""
    obj = _get_singleton()
    idx = obj._find_index(uid)
    obj._set_secret(obj.profiles[idx].PasswordSecret, password)


def get_stage(uid: str) -> str:
    """Return the profile's Stage."""
    obj = _get_singleton()
    return obj.profiles[obj._find_index(uid)].Stage


def set_stage(uid: str, stage: str) -> None:
    """Set the profile's Stage to ``'prod'`` or ``'dev'``."""
    if stage not in ("prod", "dev"):
        raise ValueError("stage must be 'prod' or 'dev'")
    obj = _get_singleton()
    idx = obj._find_index(uid)
    obj.profiles[idx].Stage = stage
    obj._save_to_disk()


def switch_profile(uid: str) -> None:
    """Make *uid* the active profile and reconfigure env vars.

    Calls :func:`ndi.cloud.logout`, then sets:

        CLOUD_API_ENVIRONMENT -> profile.Stage
        NDI_CLOUD_USERNAME    -> profile.Email
        NDI_CLOUD_PASSWORD    -> get_password(uid)

    Marks *uid* as the current profile (in memory only -- does not
    change the persisted default).
    """
    obj = _get_singleton()
    prof = obj.profiles[obj._find_index(uid)]
    try:
        from .auth import logout

        logout()
    except Exception as exc:  # noqa: BLE001 - parity with MATLAB warning
        logger.warning("logout failed during switch_profile: %s", exc)

    os.environ["CLOUD_API_ENVIRONMENT"] = prof.Stage
    os.environ["NDI_CLOUD_USERNAME"] = prof.Email
    os.environ["NDI_CLOUD_PASSWORD"] = obj._get_secret(prof.PasswordSecret)
    obj.current_uid = uid


def filename() -> Path:
    """Return the JSON profile-list path."""
    return _get_singleton().filename


def secrets_filename() -> Path:
    """Return the AES secrets file path."""
    return _get_singleton().secrets_filename


def backend() -> _BackendName:
    """Return the active secrets backend (``'keyring'``/``'aes'``/``'memory'``)."""
    return _get_singleton().backend


def use_backend(name: _BackendName) -> None:
    """Force a backend (test hook).  ``name`` must be one of
    ``'keyring'``, ``'aes'``, ``'memory'``."""
    if name not in ("keyring", "aes", "memory"):
        raise ValueError("backend must be 'keyring', 'aes', or 'memory'")
    _get_singleton().backend = name


def reload() -> None:
    """Re-read profiles and default from disk."""
    obj = _get_singleton()
    obj.profiles = []
    obj.current_uid = ""
    obj.default_uid = ""
    obj._load_from_disk()
    obj._adopt_default_as_current()


def reset() -> None:
    """Clear the in-memory singleton state.  Does NOT touch disk."""
    obj = _get_singleton()
    obj.profiles = []
    obj.current_uid = ""
    obj.default_uid = ""
    obj._memory_store = {}
