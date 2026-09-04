"""Shared eval plumbing: run the real verifier pipeline over a corpus on disk.

No database, no rail, no chain: the pipeline is pure computation, so a suite can
score it directly.  Every report records the provider that produced its numbers.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents._llm import provider_name
from app.agents.verifier.pipeline import ArtifactInput, VerificationOutput, verify
from app.evidence.analyse import analyse
from app.storage.store import sniff_content_type

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "data" / "generated"
OUT = Path(__file__).resolve().parent / "out"

LABEL_TO_DECISION = {
    "should_release": "RELEASE",
    "should_reject": "REJECT",
    "should_escalate": "ESCALATE",
}
DECISIONS = ("RELEASE", "REJECT", "ESCALATE")


@dataclass(slots=True)
class Case:
    bundle_id: str
    milestone_type: str
    label: str
    adversarial: str | None
    note: str
    condition: dict[str, Any]
    artifacts: list[ArtifactInput]

    @property
    def expected(self) -> str:
        return LABEL_TO_DECISION[self.label]


@dataclass(slots=True)
class Result:
    case: Case
    output: VerificationOutput
    wall_ms: int
    correct: bool = field(init=False)

    def __post_init__(self) -> None:
        self.correct = self.output.decision == self.case.expected


def load_corpus(folder: Path) -> list[Case]:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    cases: list[Case] = []
    for record in manifest:
        bundle_dir = folder / record["bundle_id"]
        artifacts: list[ArtifactInput] = []
        for entry in record["artifacts"]:
            path = bundle_dir / entry["filename"]
            data = path.read_bytes()
            declared = entry["mime"]
            sniffed = sniff_content_type(data, declared, entry["filename"])
            observation = analyse(data, sniffed)
            import hashlib

            artifacts.append(
                ArtifactInput(
                    artifact_id=f"{record['bundle_id']}:{entry['filename']}",
                    artifact_type=entry["artifact_type"],
                    filename=entry["filename"],
                    mime=sniffed,
                    declared_mime=declared,
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    observation=observation,
                )
            )
        cases.append(
            Case(
                bundle_id=record["bundle_id"],
                milestone_type=record["milestone_type"],
                label=record["label"],
                adversarial=record.get("adversarial"),
                note=record.get("note", ""),
                condition=record["condition"],
                artifacts=artifacts,
            )
        )
    return cases


def run_corpus(cases: list[Case]) -> list[Result]:
    results: list[Result] = []
    for case in cases:
        started = time.perf_counter()
        output = verify(condition=case.condition, artifacts=case.artifacts)
        results.append(
            Result(case=case, output=output, wall_ms=int((time.perf_counter() - started) * 1000))
        )
    return results


def confusion(results: list[Result]) -> dict[str, dict[str, int]]:
    matrix = {e: dict.fromkeys(DECISIONS, 0) for e in DECISIONS}
    for r in results:
        matrix[r.case.expected][r.output.decision] += 1
    return matrix


def false_releases(results: list[Result]) -> list[Result]:
    """A false release is unrecoverable money.  This must be empty."""
    return [
        r
        for r in results
        if r.output.decision == "RELEASE" and r.case.expected in {"REJECT", "ESCALATE"}
    ]


def provider_banner() -> dict[str, Any]:
    from app.config.settings import settings

    name = provider_name()
    return {
        "ai_provider_configured": settings.AI_PROVIDER,
        "ai_provider_effective": name,
        "is_live_model": name in {"anthropic", "groq"},
        "model_verifier": settings.AI_MODEL_VERIFIER
        if name == "anthropic"
        else (settings.GROQ_MODEL_VERIFIER if name == "groq" else "deterministic-fixture"),
        "note": (
            "Numbers below were produced by a live model."
            if name in {"anthropic", "groq"}
            else (
                "Numbers below were produced by the deterministic offline adapter "
                "(FixtureProvider): no API key was configured. It applies the published clause "
                "rubric to real parsed artifact content and has no access to the labels. Set "
                "AI_PROVIDER=anthropic (or groq) with a key and re-run `make eval` to score a "
                "live model."
            )
        ),
    }


def write_json(name: str, payload: dict[str, Any]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def write_markdown(name: str, text: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(text, encoding="utf-8")
    return path


def table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)
