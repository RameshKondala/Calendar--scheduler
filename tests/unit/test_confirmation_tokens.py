from app.services import confirmation_tokens

SECRET = "test-secret-key"


def test_issued_token_verifies_for_the_same_event_id():
    token = confirmation_tokens.issue(SECRET, "evt-123")
    assert confirmation_tokens.verify(SECRET, token, "evt-123") is True


def test_token_does_not_verify_for_a_different_event_id():
    token = confirmation_tokens.issue(SECRET, "evt-123")
    assert confirmation_tokens.verify(SECRET, token, "evt-999") is False


def test_token_does_not_verify_under_a_different_secret():
    token = confirmation_tokens.issue(SECRET, "evt-123")
    assert confirmation_tokens.verify("a-different-secret", token, "evt-123") is False


def test_tampered_token_does_not_verify():
    token = confirmation_tokens.issue(SECRET, "evt-123")
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    assert confirmation_tokens.verify(SECRET, tampered, "evt-123") is False


def test_empty_or_missing_token_does_not_verify():
    assert confirmation_tokens.verify(SECRET, "", "evt-123") is False
    assert confirmation_tokens.verify(SECRET, None, "evt-123") is False
