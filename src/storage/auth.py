"""auth — PBKDF2 password hashing + signed-cookie sessions (stdlib only).

Starlette 1.6.0's SessionMiddleware needs `itsdangerous`, which is not a
dependency here, so the session cookie is hand-rolled: HMAC-SHA256 over
`payload.b64` with a server secret, constant-time compared. Payload is
`json{b64}.sig`; expiry is baked in (unix ts), never trusted from the client.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import secrets
import time

_ITERATIONS = 100_000
_COOKIE_SEP = "."

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, _ITERATIONS)
    return "pbkdf2${}${}${}".format(_ITERATIONS, salt.hex(), dk.hex())

def verify_password(pw: str, stored: str) -> bool:
    try:
        scheme, iters, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False

def encode_session(user_id: int, username: str, secret: str,
                   ttl: int = 43_200) -> str:
    payload = {"user_id": user_id, "username": username,
               "exp": int(time.time()) + ttl}
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"),
                   hashlib.sha256).hexdigest()
    return body + _COOKIE_SEP + sig

def decode_session(token: str | None, secret: str) -> dict | None:
    """Return the signed cookie's payload, or None on any tamper/expiry/wrong
    secret. Constant-time compare against the HMAC."""
    if not token:
        return None
    try:
        body, sig = token.rsplit(_COOKIE_SEP, 1)
        expect = hmac.new(secret.encode("utf-8"), body.encode("ascii"),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
