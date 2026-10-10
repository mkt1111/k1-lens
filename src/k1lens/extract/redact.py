"""Keep API keys and request headers out of logs and error text."""

from __future__ import annotations

import logging
import os
import re

_BEARER = re.compile(r"(?i)(authorization:\s*bearer\s+)\S+")
_API_KEY_HEADER = re.compile(r"(?i)(x-api-key:\s*)\S+")
_INSTALLED = False


class SecretFilter(logging.Filter):
    """Redact live credentials wherever a log record is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


def redact_secrets(text: str) -> str:
    """Remove env keys and credential headers from ``text``."""

    redacted = text
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        secret = os.environ.get(name, "").strip()
        if len(secret) >= 8:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = _BEARER.sub(r"\1[redacted]", redacted)
    redacted = _API_KEY_HEADER.sub(r"\1[redacted]", redacted)
    return redacted


def install_secret_redaction() -> None:
    """Suppress client debug logs and scrub secrets if a logger is turned up."""

    global _INSTALLED
    if _INSTALLED:
        return
    redactor = SecretFilter()
    logging.getLogger().addFilter(redactor)
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        logger.addFilter(redactor)
    _INSTALLED = True
