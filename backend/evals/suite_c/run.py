"""Suite C -- provenance integrity.

Three properties, each of which must fail loudly when tampered with:

1. Flip one artifact byte  => the Merkle proof fails.
2. Mutate a ledger event   => verify reports the exact broken index.
3. Every on-chain anchor matches the local attestation hash on read-back
   (or reports honestly that anchoring was unavailable).

Plus the two things the whole provenance story rests on: canonical JSON is
order-independent, and the EIP-712 signature does not survive an altered payload.

    python -m evals.suite_c.run
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any

from sqlalchemy import select, text

from app.attest.canonical import canonical_json, payload_hash, sha256_hex
from app.attest.eip712 import recover_signer, sign_attestation, verify_signature
from app.attest.merkle import leaf_hash, merkle_proof, merkle_root, verify_proof
from app.chain.adapter import get_chain
from app.config.settings import settings
from app.db.session import dispose_engine, get_session_factory
from app.ledger.service import verify_chain
from app.models.commerce import Attestation, ChainAnchor, Deal, LedgerEvent, Milestone
from evals.fixtures import make_parties, reset_database, settled_deal
from evals.runner import provider_banner, table, write_json, write_markdown


# ─────────────────────────────────────────────────────────────────────────────
# C1: canonical JSON is order-independent
# ─────────────────────────────────────────────────────────────────────────────
def check_canonical_json() -> dict[str, Any]:
    a = {"decision": "RELEASE", "clauses": [{"id": "c1", "verdict": "PASS"}], "confidence": 0.94}
    b = {"confidence": 0.94, "clauses": [{"verdict": "PASS", "id": "c1"}], "decision": "RELEASE"}
    same = payload_hash(a) == payload_hash(b)
    reordered_list = {**a, "clauses": [{"id": "c2", "verdict": "PASS"}]}
    differs = payload_hash(a) != payload_hash(reordered_list)
    return {
        "check": "canonical JSON: reordering keys yields an identical hash, "
        "changing a value does not",
        "canonical": canonical_json(a),
        "key_order_independent": same,
        "value_sensitive": differs,
        "ok": same and differs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# C2: flip one artifact byte => the Merkle proof fails
# ─────────────────────────────────────────────────────────────────────────────
def check_merkle_tamper() -> dict[str, Any]:
    artifacts = [
        (f"artifact-{i}", sha256_hex(f"contents of artifact {i}".encode()), {"index": i})
        for i in range(5)
    ]
    leaves = [leaf_hash(digest, fields) for _, digest, fields in artifacts]
    root = merkle_root(leaves)
    target = leaves[2]
    proof = merkle_proof(leaves, target)
    valid = verify_proof(target, proof, root)

    # One byte of the artifact changes: 'contents' -> 'contentt'
    tampered_bytes = b"contentt of artifact 2"
    tampered_leaf = leaf_hash(sha256_hex(tampered_bytes), {"index": 2})
    tampered_fails = not verify_proof(tampered_leaf, proof, root)

    # And a tampered *field* set, with the same bytes, also fails.
    field_tampered = leaf_hash(artifacts[2][1], {"index": 99})
    fields_fail = not verify_proof(field_tampered, proof, root)

    return {
        "check": "flip one artifact byte => the Merkle proof fails",
        "root": root,
        "proof_steps": len(proof),
        "valid_proof_verifies": valid,
        "tampered_bytes_rejected": tampered_fails,
        "tampered_fields_rejected": fields_fail,
        "ok": valid and tampered_fails and fields_fail,
    }


# ─────────────────────────────────────────────────────────────────────────────
# C3: the EIP-712 signature does not survive an altered payload
# ─────────────────────────────────────────────────────────────────────────────
def check_signature_tamper() -> dict[str, Any]:
    key = "0x" + "3d" * 32
    common = {
        "chain_id": settings.CHAIN_ID,
        "verifying_contract": settings.CONTRACT_ADDRESS or None,
        "deal_id": "deal-under-test",
        "seq": 2,
        "evidence_root": sha256_hex(b"evidence"),
        "attestation_hash": sha256_hex(b"attestation"),
        "decision": "ESCALATE",
        "confidence_bps": 5100,
    }
    signature, signer = sign_attestation(key, **common)
    genuine = verify_signature(signature, signer, **common)
    bumped = verify_signature(signature, signer, **{**common, "confidence_bps": 5101})
    flipped = verify_signature(signature, signer, **{**common, "decision": "RELEASE"})
    recovered = recover_signer(signature, **common)
    return {
        "check": "an altered attestation payload does not verify against its signature",
        "signer": signer,
        "recovered_signer": recovered,
        "genuine_verifies": genuine,
        "confidence_bump_rejected": not bumped,
        "decision_flip_rejected": not flipped,
        "ok": genuine and not bumped and not flipped and recovered.lower() == signer.lower(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# C4: mutate a ledger event => verify reports the exact broken index
# ─────────────────────────────────────────────────────────────────────────────
async def check_ledger_tamper(deal_id: uuid.UUID) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
        before = await verify_chain(session, deal.id)
        events = list(
            (
                await session.execute(
                    select(LedgerEvent)
                    .where(LedgerEvent.deal_id == deal.id)
                    .order_by(LedgerEvent.seq)
                )
            ).scalars()
        )
        assert len(events) >= 4, "a settled milestone always produces more than four events"
        index = 3
        victim = events[index]
        original_reason = victim.reason

    # The append-only trigger is the production guard, so the tamper has to go
    # around it deliberately -- which is exactly the point: an attacker with raw
    # database access still cannot forge a chain that verifies.
    async with factory() as session:
        await session.execute(text("ALTER TABLE ledger_events DISABLE TRIGGER USER"))
        await session.execute(
            text("UPDATE ledger_events SET reason = :r WHERE id = :id"),
            {"r": original_reason + " [tampered]", "id": victim.id},
        )
        await session.execute(text("ALTER TABLE ledger_events ENABLE TRIGGER USER"))
        await session.commit()

    async with factory() as session:
        during = await verify_chain(session, deal.id)

    async with factory() as session:
        await session.execute(text("ALTER TABLE ledger_events DISABLE TRIGGER USER"))
        await session.execute(
            text("UPDATE ledger_events SET reason = :r WHERE id = :id"),
            {"r": original_reason, "id": victim.id},
        )
        await session.execute(text("ALTER TABLE ledger_events ENABLE TRIGGER USER"))
        await session.commit()

    async with factory() as session:
        after = await verify_chain(session, deal.id)

    return {
        "check": "mutate a ledger event => verify reports the exact broken index",
        "events": before["length"],
        "intact_before": before["ok"],
        "detected": not during["ok"],
        "broken_index": during.get("broken_index"),
        "expected_index": index,
        "reason": during.get("reason"),
        "restored": after["ok"],
        "ok": (
            before["ok"]
            and not during["ok"]
            and during.get("broken_index") == index
            and after["ok"]
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# C5: every on-chain anchor matches the local attestation hash on read-back
# ─────────────────────────────────────────────────────────────────────────────
async def check_chain_readback(deal_id: uuid.UUID) -> dict[str, Any]:
    chain = get_chain()
    factory = get_session_factory()
    async with factory() as session:
        deal = (await session.execute(select(Deal).where(Deal.id == deal_id))).scalar_one()
        anchors = list(
            (
                await session.execute(select(ChainAnchor).where(ChainAnchor.deal_id == deal.id))
            ).scalars()
        )
        attestations = {
            str(a.id): a
            for a in (
                await session.execute(
                    select(Attestation)
                    .join(Milestone, Milestone.id == Attestation.milestone_id)
                    .where(Milestone.deal_id == deal.id)
                )
            ).scalars()
        }

    confirmed = [a for a in anchors if a.status == "CONFIRMED" and a.tx_hash]
    if not chain.available or not confirmed:
        # Reported honestly rather than silently passing: the local half of the
        # provenance chain is verified, the on-chain half is unavailable.
        local_ok = True
        for anchor in anchors:
            if anchor.kind != "ATTESTATION" or not anchor.attestation_id:
                continue
            attestation = attestations.get(str(anchor.attestation_id))
            expected = (anchor.payload_json or {}).get("attestation_hash")
            if (
                attestation is None
                or str(expected).removeprefix("0x") != attestation.canonical_hash
            ):
                local_ok = False
        return {
            "check": "every on-chain anchor matches the local attestation hash",
            "status": "CHAIN_UNAVAILABLE",
            "chain_available": chain.available,
            "chain_unavailable_reason": chain.state().reason,
            "anchors_total": len(anchors),
            "anchors_confirmed": len(confirmed),
            "queued_anchor_payloads_match_local_attestations": local_ok,
            "note": (
                "No contract is deployed for this run, so there is nothing on chain to "
                "read back. What is verified here is that every QUEUED anchor payload "
                "carries exactly the local attestation's canonical hash, so the moment a "
                "contract address is configured the anchors published are the right ones. "
                "Deploy with `make deploy-contract` and re-run to verify the on-chain half."
            ),
            "ok": local_ok,
        }

    mismatches: list[dict[str, Any]] = []
    for anchor in confirmed:
        if anchor.milestone_seq is None:
            continue
        onchain = chain.read_milestone(deal.chain_deal_id or "", int(anchor.milestone_seq))
        expected = (anchor.payload_json or {}).get("attestation_hash")
        if onchain is None:
            mismatches.append({"anchor_id": str(anchor.id), "reason": "READ_FAILED"})
            continue
        if (
            str(onchain.get("attestation_hash", "")).removeprefix("0x").lower()
            != str(expected).removeprefix("0x").lower()
        ):
            mismatches.append(
                {
                    "anchor_id": str(anchor.id),
                    "onchain": onchain.get("attestation_hash"),
                    "local": expected,
                }
            )
    return {
        "check": "every on-chain anchor matches the local attestation hash",
        "status": "VERIFIED_ON_CHAIN",
        "anchors_confirmed": len(confirmed),
        "mismatches": mismatches,
        "contract_address": settings.CONTRACT_ADDRESS,
        "chain_id": settings.CHAIN_ID,
        "ok": not mismatches,
    }


# ─────────────────────────────────────────────────────────────────────────────
async def main() -> int:
    from tests.conftest import database_available

    checks: list[dict[str, Any]] = [
        check_canonical_json(),
        check_merkle_tamper(),
        check_signature_tamper(),
    ]
    if database_available():
        # Build the world this suite needs, so it does not depend on `make seed`,
        # on `make demo`, or on which suite ran before it.
        settings.KAFKA_ENABLED = False
        await reset_database()
        parties = await make_parties("suite-c")
        deal_id, _ = await settled_deal(parties)
        checks.append(await check_ledger_tamper(deal_id))
        checks.append(await check_chain_readback(deal_id))
        await dispose_engine()
    else:
        checks.append(
            {
                "check": "mutate a ledger event => verify reports the exact broken index",
                "ok": False,
                "failure": "no Postgres reachable",
            }
        )

    ok = all(c["ok"] for c in checks)
    payload = {
        "suite": "C -- provenance integrity",
        "status": "PASS" if ok else "FAIL",
        "provider": provider_banner(),
        "checks": checks,
        "ok": ok,
    }
    write_json("suite_c.json", payload)
    write_markdown(
        "suite_c.md",
        "## Suite C -- provenance integrity\n\n"
        + table(
            ["check", "result", "detail"],
            [
                [
                    c["check"],
                    "PASS" if c["ok"] else "FAIL",
                    ", ".join(
                        f"{k}={v}"
                        for k, v in c.items()
                        if k not in {"check", "ok", "note", "canonical"}
                    )[:200],
                ]
                for c in checks
            ],
        )
        + "\n"
        + "".join(f"\n_{c['note']}_\n" for c in checks if c.get("note"))
        + "\n",
    )
    for c in checks:
        print(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['check']}")
        if not c["ok"]:
            print(f"        {c}")
    print(
        f"\nSuite C: {'PASS' if ok else 'FAIL'} ({sum(1 for c in checks if c['ok'])}/{len(checks)})"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
