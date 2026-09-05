"""Evidence Merkle tree (spec §18).

Leaf content = ``sha256( sha256(artifact_bytes) || sha256(canonical_json(extracted_fields)) )``
Leaf node    = ``sha256( 0x00 || leaf_content )``
Internal node= ``sha256( 0x01 || left || right )``
Order  = leaves sorted ascending by their hex digest, so the root does not depend
         on upload order.
Duplicate-node rule = an odd node at any level is promoted by hashing it with
         **itself** (``H(0x01||n||n)``), the standard rule; documented because the
         alternative (promote unchanged) yields a different root.

**Leaves and internal nodes are domain-separated, and the tag is applied by the
verifier**, which is the part that actually does the work.  Without it a leaf and
an internal node are both a bare ``sha256`` digest of sixty-four bytes, so an
internal node can be handed back as if it were a leaf and a *shorter* proof
recomputes the same root -- the classic Merkle second-preimage forgery.
``POST /api/v1/evidence/verify`` takes a ``(leaf, proof, root)`` triple from
anyone, unauthenticated, so that forgery was reachable by anybody who knew a
bundle's published root: they could prove "inclusion" of a value that is not any
artifact's leaf.  Tagging inside :func:`verify_proof` is what closes it -- a
supplied value is hashed as a leaf before the path is walked, so a node digest
can never re-enter the tree at the level it came from.  Scheme follows RFC 6962.

The leaf *content* hash is unchanged, so ``Artifact`` rows and the ``leaf`` value
on the wire keep their meaning; the tree above it, and therefore ``merkle_root``,
does not.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.attest.canonical import canonical_bytes, sha256_hex

EMPTY_ROOT = "0" * 64

# Domain separation tags.  A leaf preimage can never equal an internal-node
# preimage: different tag, and different length.
_LEAF_TAG = b"\x00"
_NODE_TAG = b"\x01"

# A bundle holds at most a few dozen artifacts, so an honest proof is a handful
# of steps.  The bound exists because the endpoint is public and every step is a
# hash: an unbounded list is free CPU for anyone who asks.
MAX_PROOF_STEPS = 64


def _h(*parts: bytes) -> bytes:
    d = hashlib.sha256()
    for p in parts:
        d.update(p)
    return d.digest()


def leaf_hash(artifact_bytes_sha256: str, extracted_fields: Any) -> str:
    """A leaf's *content* hash, from an artifact's bytes hash and its fields."""
    a = bytes.fromhex(artifact_bytes_sha256)
    b = bytes.fromhex(
        sha256_hex(canonical_bytes(extracted_fields if extracted_fields is not None else {}))
    )
    return _h(a, b).hex()


def leaf_node(leaf: str) -> str:
    """The tagged tree node for a leaf content hash."""
    return _h(_LEAF_TAG, bytes.fromhex(leaf)).hex()


def build_tree(leaves: list[str]) -> list[list[str]]:
    """Returns every level, bottom-up.  ``levels[0]`` is the sorted leaf-node layer."""
    if not leaves:
        return [[EMPTY_ROOT]]
    level = sorted(leaf_node(leaf) for leaf in leaves)
    levels = [level]
    while len(level) > 1:
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left  # duplicate-node rule
            nxt.append(_h(_NODE_TAG, bytes.fromhex(left), bytes.fromhex(right)).hex())
        level = nxt
        levels.append(level)
    return levels


def merkle_root(leaves: list[str]) -> str:
    return build_tree(leaves)[-1][0]


def merkle_proof(leaves: list[str], target: str) -> list[dict[str, str]]:
    """Inclusion proof for ``target`` as ``[{"position": "left"|"right", "hash": hex}]``."""
    levels = build_tree(leaves)
    node = leaf_node(target)
    if node not in levels[0]:
        raise ValueError("leaf is not in the tree")
    idx = levels[0].index(node)
    proof: list[dict[str, str]] = []
    for level in levels[:-1]:
        sibling_idx = idx + 1 if idx % 2 == 0 else idx - 1
        sibling = level[sibling_idx] if sibling_idx < len(level) else level[idx]
        proof.append({"position": "right" if idx % 2 == 0 else "left", "hash": sibling})
        idx //= 2
    return proof


def verify_proof(leaf: str, proof: list[dict[str, str]], root: str) -> bool:
    """Recomputes the root from a leaf content hash and its sibling path.

    The leaf is tagged here, not trusted as a node: that is what makes an
    internal node useless as a forged leaf.  And nothing in here raises on
    hostile input -- this is reachable unauthenticated through
    ``POST /evidence/verify``, where a bad hex digit must be a ``False`` and not
    a 500.
    """
    if not isinstance(proof, list) or len(proof) > MAX_PROOF_STEPS:
        return False
    try:
        node = leaf_node(leaf)
        for step in proof:
            sib = step["hash"]
            if step["position"] == "right":
                node = _h(_NODE_TAG, bytes.fromhex(node), bytes.fromhex(sib)).hex()
            else:
                node = _h(_NODE_TAG, bytes.fromhex(sib), bytes.fromhex(node)).hex()
    except (KeyError, TypeError, ValueError):
        return False
    return node == root
