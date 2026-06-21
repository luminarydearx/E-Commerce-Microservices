"""Unit tests for audit-service PII redaction."""
import pytest

from app.services.audit_ingest import redact_pii, compute_error_fingerprint, compute_row_hash


class TestPIIRedaction:
    def test_email_redacted(self):
        text = "User email is user@example.com please check"
        redacted, changed = redact_pii(text)
        assert "[REDACTED_EMAIL]" in redacted
        assert changed is True

    def test_phone_redacted(self):
        text = "Call +6281234567890 for help"
        redacted, changed = redact_pii(text)
        assert "[REDACTED_PHONE]" in redacted
        assert changed is True

    def test_credit_card_redacted(self):
        text = "Card number 4111111111111111"
        redacted, changed = redact_pii(text)
        assert "[REDACTED_CARD]" in redacted
        assert changed is True

    def test_no_pii(self):
        text = "Server error in payment processing"
        redacted, changed = redact_pii(text)
        assert redacted == text
        assert changed is False

    def test_empty_text(self):
        redacted, changed = redact_pii("")
        assert redacted == ""
        assert changed is False

    def test_none_text(self):
        redacted, changed = redact_pii(None)
        assert redacted is None
        assert changed is False

    def test_multiple_pii_types(self):
        text = "Email: user@example.com, Phone: +6281234567890"
        redacted, changed = redact_pii(text)
        assert "[REDACTED_EMAIL]" in redacted
        assert "[REDACTED_PHONE]" in redacted
        assert changed is True


class TestErrorFingerprint:
    def test_same_error_same_fingerprint(self):
        stack1 = "Traceback (most recent call last):\n  File \"x.py\", line 10, in foo\n    bar()"
        stack2 = "Traceback (most recent call last):\n  File \"x.py\", line 10, in foo\n    bar()"
        fp1 = compute_error_fingerprint("auth-service", "ValueError", stack1)
        fp2 = compute_error_fingerprint("auth-service", "ValueError", stack2)
        assert fp1 == fp2

    def test_different_service_different_fingerprint(self):
        stack = "Traceback ..."
        fp1 = compute_error_fingerprint("auth-service", "ValueError", stack)
        fp2 = compute_error_fingerprint("order-service", "ValueError", stack)
        assert fp1 != fp2

    def test_different_error_type_different_fingerprint(self):
        stack = "Traceback ..."
        fp1 = compute_error_fingerprint("auth-service", "ValueError", stack)
        fp2 = compute_error_fingerprint("auth-service", "TypeError", stack)
        assert fp1 != fp2

    def test_fingerprint_is_md5_length(self):
        fp = compute_error_fingerprint("svc", "Err", "stack")
        assert len(fp) == 32


class TestRowHash:
    def test_same_input_same_hash(self):
        h1 = compute_row_hash("2026-01-01T00:00:00Z", "svc", "action", "user1",
                              "user", "uuid1", "", "", None)
        h2 = compute_row_hash("2026-01-01T00:00:00Z", "svc", "action", "user1",
                              "user", "uuid1", "", "", None)
        assert h1 == h2

    def test_different_input_different_hash(self):
        h1 = compute_row_hash("2026-01-01T00:00:00Z", "svc", "action1", "user1",
                              "user", "uuid1", "", "", None)
        h2 = compute_row_hash("2026-01-01T00:00:00Z", "svc", "action2", "user1",
                              "user", "uuid1", "", "", None)
        assert h1 != h2

    def test_hash_chain_dependency(self):
        # Changing prev_hash changes row_hash
        h1 = compute_row_hash("ts", "svc", "action", "u1", "user", "id1", "", "", None)
        h2 = compute_row_hash("ts", "svc", "action", "u1", "user", "id1", "", "", "prev_hash_1")
        assert h1 != h2

    def test_hash_is_sha256_length(self):
        h = compute_row_hash("ts", "svc", "action", "u1", "user", "id1", "", "", None)
        assert len(h) == 64
