"""Canonical JSON, the Merkle tree, and EIP-712 signing."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from app.attest.canonical import canonical_json, payload_hash, sha256_hex
from app.attest.eip712 import (
    ATTESTATION_TYPES,
    DOMAIN_NAME,
    DOMAIN_VERSION,
    deal_id_bytes32,
    recover_signer,
    sign_attestation,
    typed_data,
    verify_signature,
)
from app.attest.merkle import (
    EMPTY_ROOT,
    build_tree,
    leaf_hash,
    merkle_proof,
    merkle_root,
    verify_proof,
)


def test_key_order_does_not_change_the_hash():
    a = {"z": 1, "a": {"n": [1, 2], "m": "x"}, "b": None}
    b = {"b": None, "a": {"m": "x", "n": [1, 2]}, "z": 1}
    assert payload_hash(a) == payload_hash(b)
    assert canonical_json(a) == canonical_json(b)


def test_value_change_does_change_the_hash():
    a = {"confidence": 0.94}
    assert payload_hash(a) != payload_hash({"confidence": 0.95})


def test_canonical_json_has_no_insignificant_whitespace():
    assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'


def test_integers_stay_integers():
    assert canonical_json({"paise": 42_000_000}) == '{"paise":42000000}'
    assert "42000000.0" not in canonical_json({"paise": 42_000_000})


def test_float_is_rendered_stably():
    # 0.1+0.2 must not produce a different hash from 0.30000000000000004's
    # 12-significant-digit rendering of the same intended value.
    assert payload_hash({"x": 0.1 + 0.2}) == payload_hash({"x": 0.3})


def test_datetime_is_utc_iso8601_with_z():
    naive = dt.datetime(2026, 9, 4, 14, 22, 9, 123000)
    aware = naive.replace(tzinfo=dt.UTC)
    assert canonical_json({"t": aware}) == '{"t":"2026-09-04T14:22:09.123Z"}'
    # A naive datetime is treated as UTC rather than silently taking local time.
    assert canonical_json({"t": naive}) == canonical_json({"t": aware})


def test_offset_datetime_is_normalised_to_utc():
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    local = dt.datetime(2026, 9, 4, 19, 52, 9, 123000, tzinfo=ist)
    assert canonical_json({"t": local}) == '{"t":"2026-09-04T14:22:09.123Z"}'


def test_null_is_explicit():
    assert canonical_json({"human_approver": None}) == '{"human_approver":null}'


def test_decimal_and_bytes():
    assert canonical_json({"d": Decimal("0.940")}) == '{"d":"0.94"}'
    assert canonical_json({"b": b"\x00\xff"}) == '{"b":"00ff"}'


def test_nan_is_refused():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_unknown_type_is_refused():
    class Thing:
        pass

    with pytest.raises(TypeError):
        canonical_json({"x": Thing()})


@hyp_settings(max_examples=200, deadline=None)
@given(
    st.dictionaries(
        st.text(min_size=1, max_size=6),
        st.one_of(st.integers(-(10**9), 10**9), st.booleans(), st.none(), st.text(max_size=8)),
        max_size=8,
    )
)
def test_canonicalisation_is_permutation_invariant(payload):
    shuffled = dict(reversed(list(payload.items())))
    assert payload_hash(payload) == payload_hash(shuffled)


# ── Merkle ──────────────────────────────────────────────────────────────────
def _leaves(n: int) -> list[str]:
    return [leaf_hash(sha256_hex(f"artifact {i}".encode()), {"i": i}) for i in range(n)]


def test_empty_tree_root():
    assert merkle_root([]) == EMPTY_ROOT


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 8, 9, 17])
def test_every_leaf_has_a_valid_proof(count):
    leaves = _leaves(count)
    root = merkle_root(leaves)
    for leaf in leaves:
        proof = merkle_proof(leaves, leaf)
        assert verify_proof(leaf, proof, root), f"{count} leaves"


def test_root_is_independent_of_input_order():
    leaves = _leaves(6)
    assert merkle_root(leaves) == merkle_root(list(reversed(leaves)))


def test_one_flipped_byte_breaks_the_proof():
    leaves = _leaves(5)
    root = merkle_root(leaves)
    target = leaves[2]
    proof = merkle_proof(leaves, target)
    tampered = leaf_hash(sha256_hex(b"artifact 2 "), {"i": 2})
    assert verify_proof(target, proof, root)
    assert not verify_proof(tampered, proof, root)


def test_tampered_extracted_fields_break_the_proof():
    """The leaf binds the bytes AND the extracted fields, so editing a field
    after extraction is detectable even with identical bytes."""
    digest = sha256_hex(b"invoice bytes")
    honest = leaf_hash(digest, {"total": 76950})
    forged = leaf_hash(digest, {"total": 176950})
    leaves = [honest, *_leaves(3)]
    root = merkle_root(leaves)
    proof = merkle_proof(leaves, honest)
    assert verify_proof(honest, proof, root)
    assert not verify_proof(forged, proof, root)


def test_odd_node_duplicate_rule_is_stable():
    leaves = _leaves(3)
    levels = build_tree(leaves)
    assert len(levels[0]) == 3
    assert len(levels[-1]) == 1
    assert merkle_root(leaves) == merkle_root(leaves)


def test_proof_for_absent_leaf_raises():
    with pytest.raises(ValueError):
        merkle_proof(_leaves(4), "0" * 64)


# ── EIP-712 ─────────────────────────────────────────────────────────────────
KEY = "0x" + "5a" * 32
COMMON = {
    "chain_id": 84532,
    "verifying_contract": None,
    "deal_id": "D-4812",
    "seq": 1,
    "evidence_root": sha256_hex(b"root"),
    "attestation_hash": sha256_hex(b"attestation"),
    "decision": "RELEASE",
    "confidence_bps": 9400,
}


def test_signature_round_trip():
    signature, signer = sign_attestation(KEY, **COMMON)
    assert verify_signature(signature, signer, **COMMON)
    assert recover_signer(signature, **COMMON).lower() == signer.lower()


@pytest.mark.parametrize(
    "field,value",
    [
        ("confidence_bps", 9401),
        ("decision", "ESCALATE"),
        ("seq", 2),
        ("evidence_root", sha256_hex(b"other")),
        ("attestation_hash", sha256_hex(b"other")),
        ("deal_id", "D-4813"),
    ],
)
def test_any_altered_field_breaks_the_signature(field, value):
    signature, signer = sign_attestation(KEY, **COMMON)
    assert not verify_signature(signature, signer, **{**COMMON, field: value})


def test_typed_data_shape_is_pinned():
    data = typed_data(**COMMON)
    assert data["primaryType"] == "Attestation"
    assert data["domain"]["name"] == DOMAIN_NAME
    assert data["domain"]["version"] == DOMAIN_VERSION
    assert [f["name"] for f in ATTESTATION_TYPES["Attestation"]] == [
        "dealId",
        "seq",
        "evidenceRoot",
        "attestationHash",
        "decision",
        "confidenceBps",
    ]


def test_deal_id_is_hashed_not_truncated():
    """A UUID does not fit in bytes32 as text, and truncating it would create
    collisions between deals."""
    a = deal_id_bytes32("11111111-1111-1111-1111-111111111111")
    b = deal_id_bytes32("11111111-1111-1111-1111-111111111112")
    assert a != b
    assert len(a) == 66 and a.startswith("0x")


def test_bad_root_length_is_refused():
    with pytest.raises(ValueError):
        typed_data(**{**COMMON, "evidence_root": "abc"})
