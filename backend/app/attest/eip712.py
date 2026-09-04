"""EIP-712 typed-data signing of attestations (spec §18).

The contract recovers the signer on-chain, so the record proves *who* attested,
not merely that something was attested.

Domain and struct are byte-stable and must match ``contracts/src/AegisEscrow.sol``.
"""

from __future__ import annotations

from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

DOMAIN_NAME = "Aegis"
DOMAIN_VERSION = "1"

ATTESTATION_TYPES: dict[str, list[dict[str, str]]] = {
    "Attestation": [
        {"name": "dealId", "type": "bytes32"},
        {"name": "seq", "type": "uint8"},
        {"name": "evidenceRoot", "type": "bytes32"},
        {"name": "attestationHash", "type": "bytes32"},
        {"name": "decision", "type": "uint8"},
        {"name": "confidenceBps", "type": "uint16"},
    ]
}

DECISION_ENUM = {"NONE": 0, "RELEASE": 1, "REJECT": 2, "ESCALATE": 3}


def deal_id_bytes32(deal_id: str) -> str:
    """A UUID string becomes a bytes32 by keccak — never truncated."""
    return "0x" + keccak(text=str(deal_id)).hex()


def _b32(hex_or_hash: str) -> str:
    h = hex_or_hash[2:] if hex_or_hash.startswith("0x") else hex_or_hash
    if len(h) != 64:
        raise ValueError(f"expected 32 bytes, got {len(h) // 2}")
    return "0x" + h


def typed_data(
    *,
    chain_id: int,
    verifying_contract: str | None,
    deal_id: str,
    seq: int,
    evidence_root: str,
    attestation_hash: str,
    decision: str,
    confidence_bps: int,
) -> dict[str, Any]:
    contract = (
        to_checksum_address(verifying_contract)
        if verifying_contract
        else "0x0000000000000000000000000000000000000000"
    )
    return {
        "types": ATTESTATION_TYPES,
        "primaryType": "Attestation",
        "domain": {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": int(chain_id),
            "verifyingContract": contract,
        },
        "message": {
            "dealId": deal_id_bytes32(deal_id),
            "seq": int(seq),
            "evidenceRoot": _b32(evidence_root),
            "attestationHash": _b32(attestation_hash),
            "decision": DECISION_ENUM[decision],
            "confidenceBps": int(confidence_bps),
        },
    }


def sign_attestation(private_key: str, **kwargs: Any) -> tuple[str, str]:
    """Returns ``(signature_hex, signer_address)``."""
    data = typed_data(**kwargs)
    acct = Account.from_key(private_key)
    signed = acct.sign_message(encode_typed_data(full_message=data))
    return "0x" + signed.signature.hex().removeprefix("0x"), acct.address


def recover_signer(signature: str, **kwargs: Any) -> str:
    data = typed_data(**kwargs)
    return Account.recover_message(encode_typed_data(full_message=data), signature=signature)


def verify_signature(signature: str, expected_signer: str, **kwargs: Any) -> bool:
    try:
        recovered = recover_signer(signature, **kwargs)
    except Exception:
        return False
    return recovered.lower() == expected_signer.lower()
