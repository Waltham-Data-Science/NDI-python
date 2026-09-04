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
        # 0700 so a shared-workstation neighbour cannot read the AES-encrypted
        # secrets file the aes backend writes here (the key is derived from
        # hostname+username, which they may know). No-op on Windows, and
        # honoured only when the mkdir call above created the directory.
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
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
    seed = f"{host} {user} NDI Cloud".encode()
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
    # Write via os.open with 0600 so a shared-workstation neighbour cannot
    # read the AES ciphertext. The AES key is derived from hostname+username
    # (see _aes_key_bytes), which they may know. tempfile+replace so a
    # concurrent open never sees the old file at the tightened mode with the
    # wrong contents. No-op on Windows for the mode bits, atomic on all
    # POSIX filesystems.
    tmp = filename.with_suffix(filename.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(payload, indent=2))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, filename)
    # A pre-existing file may already carry a wider mode; tighten it too so a
    # first write after an upgrade does not leave 0644 behind.
    try:
        os.chmod(filename, 0o600)
    except OSError:
        pass


def _safe_field(name: str) -> str:
    """Map a secret key to a JSON-safe field name."""
    return name.replace(" ", "_").replace(":", "_")


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------


def _detect_backend() -> _BackendName:
    """Which secrets backend is usable here.

    Each probe catches more than ImportError, because "installed" and
    "usable" are different: a partially-built native extension (a
    ``cryptography`` whose ``_rust`` module cannot load, say) raises
    something else entirely -- pyo3 raises a PanicException, which is not
    even an Exception subclass, so no ordinary caller downstream could
    defend against it. Letting that escape takes down everything that
    touches the profile store, including the GUI editor, when the
    documented behaviour is to fall back to the in-memory backend.

    KeyboardInterrupt and SystemExit are re-raised: those are the user
    asking to stop, not a backend being unavailable.
    """

    def _usable(import_it) -> bool:
        try:
            import_it()
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 - see the docstring
            logger.debug("secrets backend probe failed: %s", exc)
            return False
        return True

    def _keyring() -> None:
        import keyring  # noqa: F401

    def _cryptography() -> None:
        from cryptography.hazmat.primitives.ciphers import Cipher  # noqa: F401

    if _usable(_keyring):
        return "keyring"
    if _usable(_cryptography):
        return "aes"
    logger.warning(
        "Neither 'keyring' nor 'cryptography' is usable; "
        "ndi.cloud.profile will fall back to the in-memory backend "
        "which does NOT persist secrets to disk."
    )
    return "memory"


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

    def _find_index(self, key: str) -> int:
        """Resolve *key* to a profile index.

        *key* may be a UID (exact match), a Nickname (exact match), or an
        Email (case-insensitive exact match), tried in that order. UID wins
        outright; among nickname/email matches an ambiguous result raises
        rather than silently picking one.
        """
        for i, p in enumerate(self.profiles):
            if p.UID == key:
                return i
        by_nickname = [i for i, p in enumerate(self.profiles) if p.Nickname == key]
        if len(by_nickname) == 1:
            return by_nickname[0]
        if len(by_nickname) > 1:
            candidates = ", ".join(self.profiles[i].UID for i in by_nickname)
            raise KeyError(
                f'Nickname "{key}" matches multiple profiles ({candidates}); '
                f"use the UID to disambiguate."
            )
        by_email = [i for i, p in enumerate(self.profiles) if p.Email.lower() == key.lower()]
        if len(by_email) == 1:
            return by_email[0]
        if len(by_email) > 1:
            candidates = ", ".join(self.profiles[i].UID for i in by_email)
            raise KeyError(
                f'Email "{key}" matches multiple profiles ({candidates}); '
                f"use the UID to disambiguate."
            )
        raise KeyError(f'Unknown profile "{key}" (not a UID, Nickname, or Email).')

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


def get(key: str) -> ProfileEntry:
    """Return the profile entry for *key* (UID, Nickname, or Email)."""
    obj = _get_singleton()
    return obj.profiles[obj._find_index(key)]


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


def remove(key: str) -> None:
    """Delete the profile identified by *key* (UID, Nickname, or Email) and its stored secret."""
    obj = _get_singleton()
    idx = obj._find_index(key)
    uid = obj.profiles[idx].UID
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


def set_current(key: str) -> None:
    """Set the current profile for this session (in memory only).

    *key* may be a UID, Nickname, or Email; the resolved UID is stored.
    """
    obj = _get_singleton()
    obj.current_uid = obj.profiles[obj._find_index(key)].UID


def get_default() -> ProfileEntry | None:
    """Return the persisted default profile, or None."""
    obj = _get_singleton()
    if not obj.default_uid:
        return None
    try:
        return get(obj.default_uid)
    except KeyError:
        return None


def set_default(key: str) -> None:
    """Persist the profile identified by *key* (UID, Nickname, or Email) as the default."""
    obj = _get_singleton()
    obj.default_uid = obj.profiles[obj._find_index(key)].UID
    obj._save_to_disk()


def clear_default() -> None:
    """Forget any persisted default."""
    obj = _get_singleton()
    obj.default_uid = ""
    obj._save_to_disk()


def get_password(key: str) -> str:
    """Retrieve the stored password for the profile identified by *key*."""
    obj = _get_singleton()
    idx = obj._find_index(key)
    return obj._get_secret(obj.profiles[idx].PasswordSecret)


def set_password(key: str, password: str) -> None:
    """Update the stored password for the profile identified by *key*."""
    obj = _get_singleton()
    idx = obj._find_index(key)
    obj._set_secret(obj.profiles[idx].PasswordSecret, password)


def get_stage(key: str) -> str:
    """Return the Stage of the profile identified by *key*."""
    obj = _get_singleton()
    return obj.profiles[obj._find_index(key)].Stage


def set_stage(key: str, stage: str) -> None:
    """Set the Stage of the profile identified by *key* to ``'prod'`` or ``'dev'``."""
    if stage not in ("prod", "dev"):
        raise ValueError("stage must be 'prod' or 'dev'")
    obj = _get_singleton()
    idx = obj._find_index(key)
    obj.profiles[idx].Stage = stage
    obj._save_to_disk()


def switch_profile(key: str) -> None:
    """Make the profile identified by *key* active and reconfigure env vars.

    *key* may be a UID, a Nickname, or an Email — whichever unambiguously
    identifies a saved profile. Calls :func:`ndi.cloud.logout`, then sets:

        CLOUD_API_ENVIRONMENT -> profile.Stage
        NDI_CLOUD_USERNAME    -> profile.Email
        NDI_CLOUD_PASSWORD    -> get_password(key)

    Marks the resolved profile as the current profile (in memory only --
    does not change the persisted default).
    """
    obj = _get_singleton()
    prof = obj.profiles[obj._find_index(key)]
    try:
        from .auth import logout

        logout()
    except Exception as exc:  # noqa: BLE001 - parity with MATLAB warning
        logger.warning("logout failed during switch_profile: %s", exc)

    os.environ["CLOUD_API_ENVIRONMENT"] = prof.Stage
    os.environ["NDI_CLOUD_USERNAME"] = prof.Email
    os.environ["NDI_CLOUD_PASSWORD"] = obj._get_secret(prof.PasswordSecret)
    obj.current_uid = prof.UID


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
