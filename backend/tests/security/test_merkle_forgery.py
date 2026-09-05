"""Merkle inclusion proofs must not be forgeable.

``POST /api/v1/evidence/verify`` takes a ``(leaf, proof, root)`` triple from an
unauthenticated caller, so every one of these is a live attack surface and not a
theoretical property of the hash construction.

The forgery these pin is the classic Merkle second preimage.  When leaves and
internal nodes share a preimage shape -- both a plain ``sha256`` over sixty-four
bytes -- an internal node can be presented *as* a leaf, with a proof one level
shorter, and it recomputes the published root.  Anyone who had seen a bundle's
root could then "prove" the inclusion of a value that is not any artifact's leaf,
which is the whole of what an evidence root is supposed to rule out.

The fix is RFC 6962's: tag leaves with ``0x00`` and internal nodes with ``0x01``,
and -- the half that actually does the work -- apply the leaf tag inside
:func:`verify_proof`, so a caller's ``leaf`` is hashed as a leaf before the path
is walked and a node digest can never re-enter the tree at its own level.
"""

from __future__ import annotations

import pytest

from app.attest.canonical import sha256_hex
from app.attest.merkle import (
    MAX_PROOF_STEPS,
    build_tree,
    leaf_hash,
    leaf_node,
    merkle_proof,
    merkle_root,
    verify_proof,
)


def _leaves(n: int) -> list[str]:
    return [leaf_hash(sha256_hex(f"artifact {i}".encode()), {"i": i}) for i in range(n)]


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 7, 8, 9, 16, 17])
def test_an_honest_proof_still_verifies_at_every_size(count):
    """The forgery defence is worthless if it also breaks the real proofs."""
    leaves = _leaves(count)
    root = merkle_root(leaves)
    for leaf in leaves:
        assert verify_proof(leaf, merkle_proof(leaves, leaf), root), count


def test_an_internal_node_cannot_be_passed_off_as_a_leaf():
    """The second-preimage forgery, written out.

    In a four-leaf tree the level-1 nodes are each the parent of two leaves.
    Hand one of them back as ``leaf`` together with its own sibling -- a proof of
    length one rather than two -- and an untagged verifier walks straight to the
    real root and answers ``ok``.
    """
    leaves = _leaves(4)
    levels = build_tree(leaves)
    root = merkle_root(leaves)
    assert len(levels) == 3, "expected leaf, internal and root levels"

    internal_node, its_sibling = levels[1][0], levels[1][1]
    short_proof = [{"position": "right", "hash": its_sibling}]

    assert not verify_proof(internal_node, short_proof, root)


def test_a_tagged_leaf_node_cannot_be_passed_off_as_a_leaf_content_hash():
    """The same trick one level down: replay the tagged node, not the content."""
    leaves = _leaves(4)
    root = merkle_root(leaves)
    tagged = leaf_node(leaves[0])
    assert not verify_proof(tagged, merkle_proof(leaves, leaves[0]), root)


def test_the_root_itself_is_not_an_inclusion_proof():
    """`verify_proof(root, [], root)` is the degenerate forgery: no path at all."""
    leaves = _leaves(8)
    root = merkle_root(leaves)
    assert not verify_proof(root, [], root)


def test_a_single_leaf_tree_still_verifies_and_still_refuses_its_own_root():
    leaves = _leaves(1)
    root = merkle_root(leaves)
    assert verify_proof(leaves[0], [], root)
    assert not verify_proof(root, [], root)


def test_leaves_and_internal_nodes_occupy_disjoint_hash_spaces():
    """Domain separation, asserted rather than assumed."""
    leaves = _leaves(8)
    levels = build_tree(leaves)
    leaf_layer = set(levels[0])
    for level in levels[1:]:
        assert leaf_layer.isdisjoint(level)
    # And a leaf's content hash is never its own tree node.
    for leaf in leaves:
        assert leaf_node(leaf) != leaf


def test_the_root_still_does_not_depend_on_upload_order():
    leaves = _leaves(6)
    assert merkle_root(leaves) == merkle_root(list(reversed(leaves)))


# ── hostile input reaches this unauthenticated, so it must not raise ─────────
@pytest.mark.parametrize(
    "leaf, proof",
    [
        ("not-hex-at-all", []),
        ("zz" * 32, []),
        (leaf_hash(sha256_hex(b"x"), {}), [{"position": "right", "hash": "nonsense"}]),
        (leaf_hash(sha256_hex(b"x"), {}), [{"position": "sideways", "hash": "ab" * 32}]),
        (leaf_hash(sha256_hex(b"x"), {}), [{"hash": "ab" * 32}]),
        (leaf_hash(sha256_hex(b"x"), {}), [{"position": "right"}]),
        (leaf_hash(sha256_hex(b"x"), {}), "not-a-list"),
    ],
)
def test_malformed_input_is_false_and_never_an_exception(leaf, proof):
    assert verify_proof(leaf, proof, "ab" * 32) is False


def test_an_over_long_proof_is_refused_rather_than_walked():
    """Every step is a hash, and the endpoint is public."""
    leaves = _leaves(4)
    root = merkle_root(leaves)
    step = {"position": "right", "hash": "ab" * 32}
    assert verify_proof(leaves[0], [step] * (MAX_PROOF_STEPS + 1), root) is False
