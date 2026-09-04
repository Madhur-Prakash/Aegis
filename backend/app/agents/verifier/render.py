"""Case rendering.

The volatile case payload always comes *after* the byte-stable system prompt, and
it carries a delimited JSON block so that every provider -- including the offline
fixture adapter -- reads exactly the same structured facts.  Nothing about the
expected outcome, the eval label or the milestone amount appears here.
"""

from __future__ import annotations

import json
from typing import Any

CASE_OPEN = "<<<CASE_JSON>>>"
CASE_CLOSE = "<<<END_CASE_JSON>>>"


def _block(payload: dict[str, Any]) -> str:
    return (
        f"{CASE_OPEN}\n{json.dumps(payload, indent=2, sort_keys=True, default=str)}\n{CASE_CLOSE}"
    )


def extract_case_json(user_content: str) -> dict[str, Any]:
    start = user_content.index(CASE_OPEN) + len(CASE_OPEN)
    end = user_content.index(CASE_CLOSE)
    return json.loads(user_content[start:end])


def render_extraction_case(
    *, artifact_id: str, artifact_type: str, filename: str, observation: dict[str, Any]
) -> str:
    return (
        f"Artifact {artifact_id} of declared type {artifact_type} "
        f"(filename {filename}).\n\n"
        "Deterministic analyser output follows. Extract this artifact's fields.\n\n"
        + _block(
            {
                "task": "extraction",
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "filename": filename,
                "analyser": observation,
            }
        )
    )


def render_clause_case(
    *,
    condition: dict[str, Any],
    artifacts: list[dict[str, Any]],
    precheck_results: list[dict[str, Any]],
) -> str:
    clause_lines = "\n".join(
        f"  - {c['id']} [{c['kind']}]"
        f"{' (required)' if c.get('required', True) else ' (optional)'}: {c['description']}"
        for c in condition.get("clauses", [])
    )
    return (
        "Evaluate each clause of this milestone's verification condition "
        "independently.\n\nClauses:\n"
        f"{clause_lines}\n\n"
        "The evidence bundle's extracted fields and the deterministic pre-check "
        "results follow. Return one verdict per clause id.\n\n"
        + _block(
            {
                "task": "clause_evaluation",
                "condition": condition,
                "artifacts": artifacts,
                "deterministic_prechecks": precheck_results,
            }
        )
    )


def render_arbiter_case(
    *,
    deal_terms: dict[str, Any],
    milestone: dict[str, Any],
    buyer_claim: str,
    seller_claim: str,
    artifacts: list[dict[str, Any]],
    attestations: list[dict[str, Any]],
) -> str:
    return (
        f"Dispute on milestone {milestone.get('seq')} "
        f"({milestone.get('title')}), disputed amount "
        f"{milestone.get('amount_paise')} paise.\n\n"
        "Recommend an outcome. The split must equal the disputed amount exactly.\n\n"
        + _block(
            {
                "task": "arbitration",
                "deal_terms": deal_terms,
                "milestone": milestone,
                "buyer_claim": buyer_claim,
                "seller_claim": seller_claim,
                "artifacts": artifacts,
                "prior_attestations": attestations,
            }
        )
    )
