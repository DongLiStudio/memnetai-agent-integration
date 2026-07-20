"""Minimal per-user secret storage for the MemNetAI API key."""

from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path


class SecretError(RuntimeError):
    pass


def secret_path(home: Path) -> Path:
    return home / "api-key"


def save_api_key(home: Path, api_key: str) -> Path:
    value = api_key.strip()
    if not value:
        raise SecretError("API key cannot be empty")
    path = secret_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _protect(value.encode("utf-8")) if sys.platform == "win32" else value.encode("utf-8")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    if sys.platform != "win32":
        os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    return path


def load_api_key(home: Path) -> str:
    path = secret_path(home)
    if not path.exists():
        raise SecretError("API key is not configured")
    payload = path.read_bytes()
    raw = _unprotect(payload) if sys.platform == "win32" else payload
    value = raw.decode("utf-8").strip()
    if not value:
        raise SecretError("Stored API key is empty")
    return value


def delete_api_key(home: Path) -> None:
    secret_path(home).unlink(missing_ok=True)


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_Blob, object]:
    buffer = ctypes.create_string_buffer(data)
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(data: bytes) -> bytes:
    source, keepalive = _blob(data)
    output = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise SecretError("Windows DPAPI encryption failed")
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return b"dpapi:" + base64.b64encode(encrypted)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del keepalive


def _unprotect(data: bytes) -> bytes:
    if not data.startswith(b"dpapi:"):
        raise SecretError("Secret file is not DPAPI protected")
    source, keepalive = _blob(base64.b64decode(data[6:]))
    output = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise SecretError("Windows DPAPI decryption failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)
        del keepalive
