"""``make secret-scan`` -- fail if a credential-shaped literal is committed.

This is a blunt instrument on purpose.  It looks for the shapes that actually
leak in practice -- Razorpay live keys, private keys, AWS keys, bearer tokens,
long base64 blobs assigned to a name containing ``secret``/``key``/``token`` --
and it treats an obvious placeholder as fine.

It is not a substitute for `git secrets` or a hosted scanner.  It exists so that
the single most damaging mistake in this repository (committing a working
Razorpay key or an operator private key) cannot pass CI, and so that the claim
"never commit a secret" has something enforcing it.

    python -m scripts.secret_scan
    python -m scripts.secret_scan --path ..     # scan the whole repository
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Directories that are either generated, vendored, or deliberately local-only.
SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "out",
    "cache",
    "lib",
    "broadcast",
    "generated",
    "evidence",
    "logs",
    ".claude",
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".parquet",
    ".ico",
    ".woff",
    ".woff2",
    ".mp4",
    ".mov",
    ".lock",
}

# `.env` holds a developer's real local values and is git-ignored; scanning it
# would report findings nobody can act on.  `.env.example` IS scanned, because a
# real value pasted into the example file is exactly the mistake to catch.
#
# `.verify-cookies` is a local cookie jar written by `make verify-login`.  It
# holds a genuine session token by design and is git-ignored -- the scan found it
# the first time and was right to, so it is excluded by name with the reason
# rather than by loosening the JWT rule.
SKIP_FILES = {".env", ".verify-cookies"}

PLACEHOLDER = re.compile(
    r"(?i)^(?:|x|xx+|todo|tbd|changeme|change-me|placeholder|placeholder[-_].*|"
    r"your[-_].*|example|dummy|fake|test|none|null|redacted|\*+|<.*>|\$\{.*\}|"
    r"dev-only-.*|aegis-demo-.*|0x0+)$"
)


@dataclass(frozen=True, slots=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    # Group index holding the value to placeholder-check, or 0 for the whole match.
    value_group: int = 0


RULES: tuple[Rule, ...] = (
    Rule("razorpay live key id", re.compile(r"\brzp_live_[A-Za-z0-9]{10,}")),
    # The key body is captured so a documented placeholder (`rzp_test_xxxxxxxx`)
    # passes the placeholder check while a real test key does not.  A *live* key
    # gets no such escape: the rule above matches the whole literal.
    Rule("razorpay test key id", re.compile(r"\brzp_test_([A-Za-z0-9]{14,})"), value_group=1),
    Rule("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    Rule("pem private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    # A 32-byte hex literal is only interesting when something on the line says
    # it is a key.  Solidity is full of keccak constants of exactly that shape,
    # and flagging those would train everyone to ignore this scanner.
    Rule(
        "hex private key",
        re.compile(
            r"(?i)(?:private[-_ ]?key|privkey|operator[-_ ]?key|verifier[-_ ]?key|"
            r"signer[-_ ]?key|mnemonic|seed[-_ ]?phrase).{0,40}?(0x?[a-fA-F0-9]{64})"
        ),
        value_group=1,
    ),
    Rule("anthropic api key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    Rule("openai api key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    Rule("groq api key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    Rule("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    Rule("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    Rule("google api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    Rule("jwt", re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    # A named assignment whose value looks like real entropy.
    Rule(
        "assigned credential",
        re.compile(
            r"(?i)\b(?:api[-_]?key|secret|password|passwd|private[-_]?key|token|"
            r"access[-_]?key)\b\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']"
        ),
        value_group=1,
    ),
)

# Lines carrying this marker are exempt, with the reason written next to it.
ALLOW = re.compile(r"secret-scan-allow:")


@dataclass(frozen=True, slots=True)
class Finding:
    path: Path
    line_no: int
    rule: str
    excerpt: str


def looks_like_placeholder(value: str) -> bool:
    if PLACEHOLDER.match(value.strip()):
        return True
    # A value with no digit and no mixed case is very unlikely to be entropy.
    stripped = value.strip()
    if len(stripped) < 16:
        return True
    return not any(character.isdigit() for character in stripped) and stripped.islower()


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.name in SKIP_FILES:
            continue
        files.append(path)
    return files


def scan_text(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if ALLOW.search(line):
            continue
        for rule in RULES:
            for match in rule.pattern.finditer(line):
                value = match.group(rule.value_group) or ""
                if rule.value_group and looks_like_placeholder(value):
                    continue
                excerpt = line.strip()
                if len(excerpt) > 160:
                    excerpt = excerpt[:157] + "..."
                findings.append(Finding(path, line_no, rule.name, excerpt))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        default="..",
        help="root to scan (default: the repository, one level up from backend/)",
    )
    arguments = parser.parse_args()

    root = Path(arguments.path).resolve()
    findings: list[Finding] = []
    scanned = 0

    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        findings.extend(scan_text(path, text))

    if findings:
        print(f"secret-scan: {len(findings)} finding(s)\n", file=sys.stderr)
        for finding in findings:
            relative = finding.path.relative_to(root)
            print(f"  {relative}:{finding.line_no}  {finding.rule}", file=sys.stderr)
            print(f"    {finding.excerpt}", file=sys.stderr)
        print(
            "\nIf a finding is a deliberate non-secret, append a comment containing"
            "\n`secret-scan-allow:` and the reason to that line.",
            file=sys.stderr,
        )
        return 1

    print(f"secret-scan: ok - {scanned} files scanned, no credential-shaped literal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
