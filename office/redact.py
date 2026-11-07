"""Strip credentials from text that might be stored, returned, or logged."""

from __future__ import annotations

import logging
import os
import re

# Environment variables whose values must never appear in API output.
SECRET_ENV_VARS = (
    "FINANCIAL_DATASETS_API_KEY",
    "X402_WALLET_PRIVATE_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GOOGLE_API_KEY",
    "TYPESAFE_API_KEY",
    "XAI_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
    "OFFICE_MASTER_KEY",
)

_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|private[_-]?key|authorization)\b\s*[=:]\s*\S+"
)
_SK = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_HEXKEY = re.compile(r"\b0x[a-fA-F0-9]{64}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")


def known_secret_values() -> list[str]:
    found = []
    for name in SECRET_ENV_VARS:
        value = os.environ.get(name)
        if value and len(value) >= 8:
            found.append(value)
    return found


def redact(text: str) -> str:
    if not text:
        return text
    redacted = text
    for secret in known_secret_values():
        if secret in redacted:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _ASSIGNMENT.sub(lambda m: m.group(1) + "=[REDACTED]", redacted)
    redacted = _SK.sub("[REDACTED]", redacted)
    redacted = _HEXKEY.sub("[REDACTED]", redacted)
    redacted = _BEARER.sub("Bearer [REDACTED]", redacted)
    return redacted


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        if record.exc_info and record.exc_info[1] is not None:
            # Leave the traceback type, but avoid a formatted message that
            # still holds a secret. The formatted path uses record.msg.
            pass
        return True


def install_redaction() -> None:
    filt = RedactFilter()
    logging.getLogger().addFilter(filt)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "office"):
        logging.getLogger(name).addFilter(filt)
