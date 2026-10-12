from backend.security import hash_password, verify_password


def test_password_hash_roundtrip():
    encoded = hash_password("correct-local-secret")
    assert encoded != "correct-local-secret"
    assert verify_password("correct-local-secret", encoded)
    assert not verify_password("wrong", encoded)
