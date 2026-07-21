import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Iterable

from .security import CredentialGuard


@dataclass(frozen=True)
class Finding:
    entity_type: str
    start: int
    end: int
    confidence: float
    fingerprint: str

    def as_dict(self):
        return {
            "entity_type": self.entity_type,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class Replacement:
    entity_type: str
    start: int
    end: int
    replacement: str
    fingerprint: str

    def as_dict(self):
        return {
            "entity_type": self.entity_type,
            "start": self.start,
            "end": self.end,
            "replacement": self.replacement,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class DeidentificationResult:
    safe_text: str
    findings: tuple[Finding, ...]
    replacements: tuple[Replacement, ...]
    blocked: bool = False
    reason: str = ""

    def as_dict(self):
        return {
            "safe_text": self.safe_text,
            "findings": [finding.as_dict() for finding in self.findings],
            "replacements": [replacement.as_dict() for replacement in self.replacements],
            "blocked": self.blocked,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Recognizer:
    entity_type: str
    pattern: re.Pattern
    confidence: float


_CYR_WORD = r"[А-ЯЁ][а-яё]+"
_RECOGNIZERS = (
    Recognizer(
        "EMAIL",
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        0.99,
    ),
    Recognizer(
        "PHONE",
        re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{8,}\d)(?!\w)"),
        0.82,
    ),
    Recognizer(
        "DATE",
        re.compile(r"\b(?:\d{2}[./-]\d{2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})\b"),
        0.74,
    ),
    Recognizer(
        "SNILS",
        re.compile(r"(?i)(?:\bснилс\b\s*[:№#-]?\s*)?\b\d{3}[-\s]?\d{3}[-\s]?\d{3}[-\s]?\d{2}\b"),
        0.9,
    ),
    Recognizer(
        "PASSPORT",
        re.compile(r"(?i)(?:\bпаспорт\b|\bсерия\b|\bномер\b)\s*[:№#-]?\s*\d{2}\s?\d{2}\s?\d{6}\b|\b\d{4}\s?\d{6}\b"),
        0.78,
    ),
    Recognizer(
        "POLICY",
        re.compile(r"(?i)(?:\bполис\b|\bомс\b|\bdms\b|\bpolicy\b)\s*[:№#-]?\s*[A-ZА-ЯЁ0-9 -]{6,32}\b"),
        0.82,
    ),
    Recognizer(
        "PATIENT_ID",
        re.compile(r"(?i)(?:\bпациент\b|\bpatient\b)\s*(?:id|ид|код|#|№)?\s*[:#№-]?\s*[A-ZА-ЯЁ0-9_-]{3,32}\b"),
        0.88,
    ),
    Recognizer(
        "RU_FULL_NAME",
        re.compile(rf"(?i)(?:\bфио\b\s*[:#№-]?\s*)?{_CYR_WORD}\s+{_CYR_WORD}(?:\s+{_CYR_WORD})?"),
        0.7,
    ),
)


def pseudonymize_value(value: str, *, secret_key: str | bytes, entity_type: str, length: int = 12) -> str:
    key = _normalize_secret(secret_key)
    digest = hmac.new(key, f"{entity_type}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"[{entity_type}:{digest[:length]}]"


def detect_pii(text: str, *, secret_key: str | bytes = b"") -> tuple[Finding, ...]:
    text = text or ""
    key = _normalize_secret(secret_key) if secret_key else b""
    findings = []
    for recognizer in _RECOGNIZERS:
        for match in recognizer.pattern.finditer(text):
            value = match.group(0)
            if not _passes_entity_filter(recognizer.entity_type, value):
                continue
            findings.append(
                Finding(
                    entity_type=recognizer.entity_type,
                    start=match.start(),
                    end=match.end(),
                    confidence=recognizer.confidence,
                    fingerprint=_fingerprint(value, recognizer.entity_type, key),
                )
            )
    return tuple(_select_non_overlapping(findings))


def redact_text(text: str, *, replacement_template: str = "[{entity_type}]") -> DeidentificationResult:
    dlp_result = CredentialGuard().scan_text(text or "")
    if dlp_result.blocked:
        return DeidentificationResult(
            safe_text="",
            findings=(),
            replacements=(),
            blocked=True,
            reason=dlp_result.reason,
        )

    findings = detect_pii(text)
    return _replace_findings(text or "", findings, replacement_template=replacement_template)


def deidentify_text(text: str, *, secret_key: str | bytes) -> DeidentificationResult:
    dlp_result = CredentialGuard().scan_text(text or "")
    if dlp_result.blocked:
        return DeidentificationResult(
            safe_text="",
            findings=(),
            replacements=(),
            blocked=True,
            reason=dlp_result.reason,
        )
    _normalize_secret(secret_key)
    findings = detect_pii(text, secret_key=secret_key)
    return _replace_findings(text or "", findings, secret_key=secret_key)


def _replace_findings(
    text: str,
    findings: Iterable[Finding],
    *,
    secret_key: str | bytes = b"",
    replacement_template: str = "[{entity_type}]",
) -> DeidentificationResult:
    output = []
    replacements = []
    cursor = 0
    key = _normalize_secret(secret_key) if secret_key else b""

    for finding in findings:
        output.append(text[cursor : finding.start])
        original = text[finding.start : finding.end]
        replacement = (
            pseudonymize_value(original, secret_key=key, entity_type=finding.entity_type)
            if key
            else replacement_template.format(entity_type=finding.entity_type)
        )
        output.append(replacement)
        replacements.append(
            Replacement(
                entity_type=finding.entity_type,
                start=finding.start,
                end=finding.end,
                replacement=replacement,
                fingerprint=finding.fingerprint,
            )
        )
        cursor = finding.end

    output.append(text[cursor:])
    return DeidentificationResult(
        safe_text="".join(output),
        findings=tuple(findings),
        replacements=tuple(replacements),
    )


def _select_non_overlapping(findings: Iterable[Finding]):
    selected: list[Finding] = []
    for finding in sorted(findings, key=lambda item: (item.start, -(item.end - item.start), -item.confidence)):
        if any(finding.start < existing.end and finding.end > existing.start for existing in selected):
            continue
        selected.append(finding)
    return sorted(selected, key=lambda item: item.start)


def _passes_entity_filter(entity_type: str, value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if entity_type == "PHONE":
        return 10 <= len(digits) <= 15
    if entity_type == "SNILS":
        return len(digits) == 11
    if entity_type == "PASSPORT":
        return len(digits) == 10
    if entity_type == "RU_FULL_NAME":
        words = value.split(":", 1)[-1].split()
        return 2 <= len(words) <= 3 and all(re.fullmatch(_CYR_WORD, word) for word in words)
    return True


def _fingerprint(value: str, entity_type: str, key: bytes) -> str:
    if key:
        digest = hmac.new(key, f"{entity_type}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
    else:
        digest = hashlib.sha256(f"{entity_type}:{value}".encode("utf-8")).hexdigest()
    return digest[:16]


def _normalize_secret(secret_key: str | bytes) -> bytes:
    if isinstance(secret_key, str):
        secret_key = secret_key.encode("utf-8")
    if not isinstance(secret_key, bytes) or not secret_key:
        raise ValueError("A non-empty pseudonymization secret key is required.")
    return secret_key
