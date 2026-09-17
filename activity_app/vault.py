"""AES-GCM vault keys: Windows user DPAPI; private key file on Linux."""

import ctypes
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def dpapi(data, decrypt=False):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError("The local Windows vault key could not be unlocked.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, wintypes.HLOCAL))


class Vault:
    def __init__(self, root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / "vault.key"
        if path.exists():
            wrapped = path.read_bytes()
            if wrapped[:4] == b"DPA1" and os.name == "nt":
                key = dpapi(wrapped[4:], decrypt=True)
            elif wrapped[:4] == b"POS1" and os.name != "nt":
                key = wrapped[4:]
            else:
                raise OSError("This vault belongs to another operating system or Windows account.")
        else:
            key = AESGCM.generate_key(bit_length=256)
            wrapped = b"DPA1" + dpapi(key) if os.name == "nt" else b"POS1" + key
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(wrapped)
        self.cipher = AESGCM(key)

    def seal(self, value, purpose):
        nonce = os.urandom(12)
        return nonce + self.cipher.encrypt(nonce, value, purpose.encode())

    def open(self, value, purpose):
        return self.cipher.decrypt(value[:12], value[12:], purpose.encode())
