from __future__ import annotations

import os
import re

from security.audit import audit_event


_REDACT_ENABLED = os.getenv("AGENT_REDACT", "true").lower() == "true"

VENDOR_PREFIXES = [
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"SG\.[A-Za-z0-9_-]{20,}",
    r"xoxb-[A-Za-z0-9-]{20,}",
]
_COMPILED = [re.compile(pattern) for pattern in VENDOR_PREFIXES]


def redact(text: str) -> str:
    if not _REDACT_ENABLED:
        return text
    redacted = text
    hits = 0
    for pattern in _COMPILED:
        redacted, count = pattern.subn("[REDACTED_SECRET]", redacted)
        hits += count
    if hits:
        audit_event("redact.hit", {"count": hits}, "info")
    return redacted
