import re
from dataclasses import dataclass
from typing import Iterable


class SecretLeakDetected(ValueError):
    def __init__(self, findings: Iterable["SecretFinding"]):
        self.findings = tuple(findings)
        super().__init__("Sensitive credential material was detected.")


@dataclass(frozen=True)
class SecretFinding:
    finding_type: str
    start: int
    end: int
    reason: str
    confidence: float = 0.9

    def as_dict(self):
        return {
            "type": self.finding_type,
            "start": self.start,
            "end": self.end,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class DLPResult:
    blocked: bool
    reason: str
    findings: tuple[SecretFinding, ...]

    def as_dict(self):
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "findings": [finding.as_dict() for finding in self.findings],
        }


class CredentialGuard:
    _PRIVATE_KEY_RE = re.compile(
        r"-----BEGIN\s+(?:[A-Z0-9 ]+\s+)?PRIVATE\s+KEY-----.*?-----END\s+(?:[A-Z0-9 ]+\s+)?PRIVATE\s+KEY-----",
        re.IGNORECASE | re.DOTALL,
    )
    _ASSIGNMENT_RE = re.compile(
        r"""(?ix)
        (?P<key>
            password|passwd|pwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|
            auth[_-]?token|bearer[_-]?token|client[_-]?secret|private[_-]?key
        )
        \s*(?:=|:|=>)\s*
        (?P<quote>["']?)
        (?P<value>[^\s"',;{}]{8,}|[^"']{12,})
        (?P=quote)
        """,
    )
    _BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b")
    _TOKEN_RE = re.compile(
        r"""(?x)
        \b(?:
            sk-[A-Za-z0-9_-]{16,}|
            gh[pousr]_[A-Za-z0-9_]{24,}|
            xox[baprs]-[A-Za-z0-9-]{20,}|
            AKIA[0-9A-Z]{16}
        )\b
        """,
    )
    _CONNECTION_STRING_RE = re.compile(
        r"""(?ix)
        \b(?:
            postgresql|postgres|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|mssql|sqlserver
        )://
        [^\s/@:]+
        :
        [^\s/@]{6,}
        @
        [^\s]+
        """
    )

    def scan_text(self, text: str) -> DLPResult:
        findings = tuple(_dedupe_secret_findings(self._iter_findings(text or "")))
        blocked = bool(findings)
        reason = "credential_material_detected" if blocked else ""
        return DLPResult(blocked=blocked, reason=reason, findings=findings)

    def assert_safe_text(self, text: str) -> None:
        result = self.scan_text(text)
        if result.blocked:
            raise SecretLeakDetected(result.findings)

    def _iter_findings(self, text: str):
        for match in self._PRIVATE_KEY_RE.finditer(text):
            yield SecretFinding("private_key", match.start(), match.end(), "private key block")
        for match in self._CONNECTION_STRING_RE.finditer(text):
            yield SecretFinding("connection_string", match.start(), match.end(), "credentialed connection string")
        for match in self._ASSIGNMENT_RE.finditer(text):
            key = match.group("key").lower().replace("_", "-")
            yield SecretFinding("credential_assignment", match.start(), match.end(), f"{key} assignment")
        for match in self._BEARER_RE.finditer(text):
            yield SecretFinding("bearer_token", match.start(), match.end(), "bearer token")
        for match in self._TOKEN_RE.finditer(text):
            yield SecretFinding("api_token", match.start(), match.end(), "well-known token shape")


def _dedupe_secret_findings(findings: Iterable[SecretFinding]):
    selected: list[SecretFinding] = []
    for finding in sorted(findings, key=lambda item: (item.start, -(item.end - item.start))):
        if any(finding.start >= existing.start and finding.end <= existing.end for existing in selected):
            continue
        selected.append(finding)
    return selected


def scan_for_secrets(text: str) -> DLPResult:
    return CredentialGuard().scan_text(text)


def assert_no_secrets(text: str) -> None:
    CredentialGuard().assert_safe_text(text)
