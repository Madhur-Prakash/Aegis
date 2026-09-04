"""Evidence Merkle tree (spec §18).

Leaf   = ``sha256( sha256(artifact_bytes) || sha256(canonical_json(extracted_fields)) )``
Order  = leaves sorted ascending by their hex digest, so the root does not depend
         on upload order.
Duplicate-node rule = an odd node at any level is promoted by hashing it with
         **itself** (``H(n||n)``), the standard rule; documented because the
         alternative (promote unchanged) yields a different root.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.attest.canonical import canonical_bytes, sha256_hex

EMPTY_ROOT = "0" * 64


def _h(*parts: bytes) -> bytes:
    d = hashlib.sha256()
    for p in parts:
        d.update(p)
    return d.digest()


def leaf_hash(artifact_bytes_sha256: str, extracted_fields: Any) -> str:
    """A leaf from an artifact's content hash and its extracted fields."""
    a = bytes.fromhex(artifact_bytes_sha256)
    b = bytes.fromhex(
        sha256_hex(canonical_bytes(extracted_fields if extracted_fields is not None else {}))
    )
    return _h(a, b).hex()


def build_tree(leaves: list[str]) -> list[list[str]]:
    """Returns every level, bottom-up.  ``levels[0]`` is the sorted leaf layer."""
    if not leaves:
        return [[EMPTY_ROOT]]
    level = sorted(leaves)
    levels = [level]
    while len(level) > 1:
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left  # duplicate-node rule
            nxt.append(_h(bytes.fromhex(left), bytes.fromhex(right)).hex())
        level = nxt
        levels.append(level)
    return levels


def merkle_root(leaves: list[str]) -> str:
    return build_tree(leaves)[-1][0]


def merkle_proof(leaves: list[str], target: str) -> list[dict[str, str]]:
    """Inclusion proof for ``target`` as ``[{"position": "left"|"right", "hash": hex}]``."""
    levels = build_tree(leaves)
    if target not in levels[0]:
        raise ValueError("leaf is not in the tree")
    idx = levels[0].index(target)
    proof: list[dict[str, str]] = []
    for level in levels[:-1]:
        sibling_idx = idx + 1 if idx % 2 == 0 else idx - 1
        sibling = level[sibling_idx] if sibling_idx < len(level) else level[idx]
        proof.append({"position": "right" if idx % 2 == 0 else "left", "hash": sibling})
        idx //= 2
    return proof


def verify_proof(leaf: str, proof: list[dict[str, str]], root: str) -> bool:
    node = leaf
    for step in proof:
        sib = step["hash"]
        if step["position"] == "right":
            node = _h(bytes.fromhex(node), bytes.fromhex(sib)).hex()
        else:
            node = _h(bytes.fromhex(sib), bytes.fromhex(node)).hex()
    return node == root
