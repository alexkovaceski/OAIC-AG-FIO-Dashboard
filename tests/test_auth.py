# tests/test_auth.py
from storage import auth

def test_hash_and_verify():
    h = auth.hash_password("correct horse")
    assert h.startswith("pbkdf2$")
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("wrong", h)

def test_hash_is_salted():
    assert auth.hash_password("same") != auth.hash_password("same")

def test_session_roundtrip():
    tok = auth.encode_session(7, "alice", "viewer", "s3cret")
    payload = auth.decode_session(tok, "s3cret")
    assert payload and payload["user_id"] == 7 and payload["username"] == "alice"

def test_session_tamper_detected():
    tok = auth.encode_session(7, "alice", "viewer", "s3cret")
    tampered = tok[:-1] + ("0" if tok[-1] != "0" else "1")
    assert auth.decode_session(tampered, "s3cret") is None

def test_session_expired():
    tok = auth.encode_session(7, "alice", "viewer", "s3cret", ttl=-1)
    assert auth.decode_session(tok, "s3cret") is None

def test_session_wrong_secret():
    tok = auth.encode_session(7, "alice", "viewer", "right")
    assert auth.decode_session(tok, "wrong") is None

def test_encode_session_carries_role():
    token = auth.encode_session(1, "alice", "internal", "test-secret")
    payload = auth.decode_session(token, "test-secret")
    assert payload["role"] == "internal"
