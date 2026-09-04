"""Contract adapter.

I7: every argument is ``bytes32``, an integer, an enum or a signature.  The
adapter's public methods accept nothing else -- names, emails, addresses,
documents, invoice contents, messages and raw evidence cannot physically be
passed through this interface, and a lint test asserts the signatures.

A chain RPC failure never rolls back a settled payout: the anchor is queued in
``chain_anchors`` and retried visibly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.common.errors import ChainUnavailable
from app.common.logging import get_logger
from app.config.settings import settings

log = get_logger("chain")

DECISION_ENUM = {"NONE": 0, "RELEASE": 1, "REJECT": 2, "ESCALATE": 3}
_BYTES32 = re.compile(r"^0x[0-9a-fA-F]{64}$")

ABI: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "openDeal",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "dealId", "type": "bytes32"},
            {"name": "termsHash", "type": "bytes32"},
            {"name": "buyer", "type": "address"},
            {"name": "seller", "type": "address"},
            {"name": "milestoneCount", "type": "uint8"},
            {"name": "disputeWindowEnds", "type": "uint64"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "anchorAttestation",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "dealId", "type": "bytes32"},
            {"name": "seq", "type": "uint8"},
            {"name": "evidenceRoot", "type": "bytes32"},
            {"name": "attestationHash", "type": "bytes32"},
            {"name": "decision", "type": "uint8"},
            {"name": "confidenceBps", "type": "uint16"},
            {"name": "verifierSig", "type": "bytes"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "recordSettlement",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "dealId", "type": "bytes32"},
            {"name": "seq", "type": "uint8"},
            {"name": "amountPaise", "type": "uint64"},
            {"name": "railRef", "type": "bytes32"},
            {"name": "humanApproved", "type": "bool"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "raiseDispute",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "dealId", "type": "bytes32"}, {"name": "seq", "type": "uint8"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "resolveDispute",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "dealId", "type": "bytes32"},
            {"name": "seq", "type": "uint8"},
            {"name": "releasePaise", "type": "uint64"},
            {"name": "refundPaise", "type": "uint64"},
            {"name": "decisionHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "getMilestone",
        "stateMutability": "view",
        "inputs": [{"name": "dealId", "type": "bytes32"}, {"name": "seq", "type": "uint8"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "evidenceRoot", "type": "bytes32"},
                    {"name": "attestationHash", "type": "bytes32"},
                    {"name": "decision", "type": "uint8"},
                    {"name": "confidenceBps", "type": "uint16"},
                    {"name": "settledAmountPaise", "type": "uint64"},
                    {"name": "railRef", "type": "bytes32"},
                    {"name": "humanApproved", "type": "bool"},
                    {"name": "attestor", "type": "address"},
                ],
            }
        ],
    },
]


def require_bytes32(value: str, name: str) -> str:
    text = value if value.startswith("0x") else f"0x{value}"
    if not _BYTES32.match(text):
        raise ValueError(f"{name} must be a 32-byte hex value, got {value!r}")
    return text


def require_uint(value: int, bits: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value >= 2**bits:
        raise ValueError(f"{name} must be a uint{bits}")
    return value


@dataclass(slots=True)
class ChainTx:
    tx_hash: str
    block_number: int | None
    explorer_url: str


@dataclass(slots=True)
class ChainState:
    available: bool
    reason: str | None
    contract_address: str | None
    chain_id: int
    rpc_url: str


class ChainAdapter:
    """Thin wrapper over web3.  Never holds application state."""

    def __init__(self) -> None:
        self._w3: Any = None
        self._contract: Any = None
        self._account: Any = None
        self._reason: str | None = None
        self._connect()

    # ── setup ──────────────────────────────────────────────────────────
    def _connect(self) -> None:
        if not settings.CHAIN_ENABLED:
            self._reason = "CHAIN_DISABLED"
            return
        if not settings.CONTRACT_ADDRESS:
            self._reason = "CONTRACT_ADDRESS_NOT_SET"
            return
        if not settings.OPERATOR_PRIVATE_KEY:
            self._reason = "OPERATOR_KEY_NOT_SET"
            return
        try:
            from eth_account import Account
            from web3 import Web3

            self._w3 = Web3(
                Web3.HTTPProvider(settings.BLOCKCHAIN_RPC_URL, request_kwargs={"timeout": 15})
            )
            if not self._w3.is_connected():
                self._reason = "RPC_UNREACHABLE"
                self._w3 = None
                return
            self._account = Account.from_key(settings.OPERATOR_PRIVATE_KEY)
            self._contract = self._w3.eth.contract(
                address=Web3.to_checksum_address(settings.CONTRACT_ADDRESS), abi=ABI
            )
            log.info(
                "chain adapter ready",
                extra={"chain_id": settings.CHAIN_ID, "contract": settings.CONTRACT_ADDRESS},
            )
        except Exception as exc:
            self._reason = f"CONNECT_FAILED:{type(exc).__name__}"
            self._w3 = None

    @property
    def available(self) -> bool:
        return self._contract is not None and self._w3 is not None

    def state(self) -> ChainState:
        return ChainState(
            available=self.available,
            reason=None if self.available else self._reason,
            contract_address=settings.CONTRACT_ADDRESS or None,
            chain_id=settings.CHAIN_ID,
            rpc_url=settings.BLOCKCHAIN_RPC_URL,
        )

    def explorer_url(self, tx_hash: str) -> str:
        base = "https://sepolia.basescan.org" if settings.CHAIN_ID == 84532 else ""
        return f"{base}/tx/{tx_hash}" if base else tx_hash

    # ── writes ─────────────────────────────────────────────────────────
    def _send(self, fn: Any, label: str) -> ChainTx:
        if not self.available:
            raise ChainUnavailable(details={"reason": self._reason})
        try:
            nonce = self._w3.eth.get_transaction_count(self._account.address)
            tx = fn.build_transaction(
                {
                    "from": self._account.address,
                    "nonce": nonce,
                    "chainId": settings.CHAIN_ID,
                    "gas": 500_000,
                    "maxFeePerGas": self._w3.to_wei("0.3", "gwei"),
                    "maxPriorityFeePerGas": self._w3.to_wei("0.05", "gwei"),
                }
            )
            signed = self._account.sign_transaction(tx)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            hex_hash = tx_hash.hex()
            if not hex_hash.startswith("0x"):
                hex_hash = f"0x{hex_hash}"
            log.info(
                "chain write",
                extra={"call": label, "tx": hex_hash, "block": receipt["blockNumber"]},
            )
            return ChainTx(hex_hash, int(receipt["blockNumber"]), self.explorer_url(hex_hash))
        except ChainUnavailable:
            raise
        except Exception as exc:
            log.warning("chain write failed", extra={"call": label, "error": type(exc).__name__})
            raise ChainUnavailable(
                message="The chain write failed and has been queued for retry.",
                details={"call": label, "error": type(exc).__name__},
            ) from exc

    def open_deal(
        self,
        deal_id_b32: str,
        terms_hash: str,
        buyer: str,
        seller: str,
        milestone_count: int,
        dispute_window_ends: int,
    ) -> ChainTx:
        from web3 import Web3

        return self._send(
            self._contract.functions.openDeal(
                require_bytes32(deal_id_b32, "dealId"),
                require_bytes32(terms_hash, "termsHash"),
                Web3.to_checksum_address(buyer),
                Web3.to_checksum_address(seller),
                require_uint(milestone_count, 8, "milestoneCount"),
                require_uint(dispute_window_ends, 64, "disputeWindowEnds"),
            ),
            "openDeal",
        )

    def anchor_attestation(
        self,
        deal_id_b32: str,
        seq: int,
        evidence_root: str,
        attestation_hash: str,
        decision: str,
        confidence_bps: int,
        verifier_sig: str,
    ) -> ChainTx:
        return self._send(
            self._contract.functions.anchorAttestation(
                require_bytes32(deal_id_b32, "dealId"),
                require_uint(seq, 8, "seq"),
                require_bytes32(evidence_root, "evidenceRoot"),
                require_bytes32(attestation_hash, "attestationHash"),
                DECISION_ENUM[decision],
                require_uint(confidence_bps, 16, "confidenceBps"),
                bytes.fromhex(verifier_sig.removeprefix("0x")),
            ),
            "anchorAttestation",
        )

    def record_settlement(
        self,
        deal_id_b32: str,
        seq: int,
        amount_paise: int,
        rail_ref_hash: str,
        human_approved: bool,
    ) -> ChainTx:
        return self._send(
            self._contract.functions.recordSettlement(
                require_bytes32(deal_id_b32, "dealId"),
                require_uint(seq, 8, "seq"),
                require_uint(amount_paise, 64, "amountPaise"),
                require_bytes32(rail_ref_hash, "railRef"),
                bool(human_approved),
            ),
            "recordSettlement",
        )

    def resolve_dispute(
        self,
        deal_id_b32: str,
        seq: int,
        release_paise: int,
        refund_paise: int,
        decision_hash: str,
    ) -> ChainTx:
        return self._send(
            self._contract.functions.resolveDispute(
                require_bytes32(deal_id_b32, "dealId"),
                require_uint(seq, 8, "seq"),
                require_uint(release_paise, 64, "releasePaise"),
                require_uint(refund_paise, 64, "refundPaise"),
                require_bytes32(decision_hash, "decisionHash"),
            ),
            "resolveDispute",
        )

    def raise_dispute(self, deal_id_b32: str, seq: int) -> ChainTx:
        return self._send(
            self._contract.functions.raiseDispute(
                require_bytes32(deal_id_b32, "dealId"), require_uint(seq, 8, "seq")
            ),
            "raiseDispute",
        )

    # ── reads ──────────────────────────────────────────────────────────
    def read_milestone(self, deal_id_b32: str, seq: int) -> dict[str, Any] | None:
        if not self.available:
            return None
        try:
            record = self._contract.functions.getMilestone(
                require_bytes32(deal_id_b32, "dealId"), require_uint(seq, 8, "seq")
            ).call()
        except Exception as exc:
            log.warning("chain read failed", extra={"error": type(exc).__name__})
            return None
        inverse = {v: k for k, v in DECISION_ENUM.items()}
        return {
            "evidence_root": record[0].hex() if isinstance(record[0], bytes) else str(record[0]),
            "attestation_hash": record[1].hex() if isinstance(record[1], bytes) else str(record[1]),
            "decision": inverse.get(int(record[2]), "NONE"),
            "confidence_bps": int(record[3]),
            "settled_amount_paise": int(record[4]),
            "rail_ref": record[5].hex() if isinstance(record[5], bytes) else str(record[5]),
            "human_approved": bool(record[6]),
            "attestor": str(record[7]),
        }


_adapter: ChainAdapter | None = None


def get_chain() -> ChainAdapter:
    global _adapter
    if _adapter is None:
        _adapter = ChainAdapter()
    return _adapter


def reset_chain() -> None:
    global _adapter
    _adapter = None
