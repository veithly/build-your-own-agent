from __future__ import annotations

import base64
import re
from dataclasses import dataclass

from security.audit import audit_event


INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\U000e0000-\U000e007f]")
SUSPICIOUS_RE = re.compile(
    r"(ignore previous|forget instructions|system:|developer:|jailbreak|"
    r"curl\s+.+\|\s*(sh|bash)|rm\s+-rf|powershell\s+-enc|cmd\.exe\s+/c)",
    re.IGNORECASE,
)
MAX_KEY_CHARS = 200
MAX_VALUE_CHARS = 2200


@dataclass
class ScanResult:
    allowed: bool
    reason: str = "allow"


def scan_persistent_text(key: str, value: str, *, fail_open: bool = True) -> ScanResult:
    try:
        if len(key) > MAX_KEY_CHARS:
            return _deny("key_too_long")
        if len(value) > MAX_VALUE_CHARS:
            return _deny("value_too_long")
        joined = f"{key}\n{value}"
        if INVISIBLE_RE.search(joined):
            return _deny("invisible_unicode")
        if SUSPICIOUS_RE.search(joined):
            return _deny("prompt_or_shell_payload")
        if _looks_like_large_base64(value):
            return _deny("large_base64_blob")
        return ScanResult(True)
    except Exception as exc:
        audit_event("scanner.fail_open", {"error": repr(exc)}, "warn")
        return ScanResult(True, "scanner_error_fail_open" if fail_open else "scanner_error")


def _deny(reason: str) -> ScanResult:
    audit_event("scanner.reject", {"reason": reason}, "warn")
    return ScanResult(False, reason)


def _looks_like_large_base64(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if len(compact) < 512 or len(compact) % 4 != 0:
        return False
    if not re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
        return False
    try:
        decoded = base64.b64decode(compact, validate=True)
    except Exception:
        return False
    return len(decoded) >= 384
