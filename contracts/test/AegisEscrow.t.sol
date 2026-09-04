// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AegisEscrow} from "../src/AegisEscrow.sol";

contract AegisEscrowTest is Test {
    AegisEscrow internal escrow;

    address internal operator = address(0xA11CE);
    address internal buyer = address(0xB0B);
    address internal seller = address(0xC0DE);
    address internal stranger = address(0xDEAD);

    uint256 internal verifierPk = 0x2c777777777777777777777777777777777777777777777777777777777777;
    address internal verifier;

    bytes32 internal dealId = keccak256("deal-D-4812");
    bytes32 internal termsHash = keccak256("terms-v1");
    bytes32 internal evidenceRoot = keccak256("evidence-root");
    bytes32 internal attestationHash = keccak256("attestation-canonical");

    function setUp() public {
        vm.prank(operator);
        escrow = new AegisEscrow(operator);
        verifier = vm.addr(verifierPk);
    }

    function _open(uint8 count, uint64 windowEnds) internal {
        vm.prank(operator);
        escrow.openDeal(dealId, termsHash, buyer, seller, count, windowEnds);
    }

    function _sign(
        uint8 seq,
        bytes32 root,
        bytes32 hash_,
        AegisEscrow.Decision decision,
        uint16 bps
    ) internal view returns (bytes memory) {
        bytes32 digest = escrow.attestationDigest(dealId, seq, root, hash_, decision, bps);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(verifierPk, digest);
        return abi.encodePacked(r, s, v);
    }

    // ── only-operator enforcement ───────────────────────────────────────────
    function test_openDeal_onlyOperator() public {
        vm.prank(stranger);
        vm.expectRevert(AegisEscrow.NotOperator.selector);
        escrow.openDeal(dealId, termsHash, buyer, seller, 3, 0);
    }

    function test_anchor_onlyOperator() public {
        _open(3, 0);
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400);
        vm.prank(stranger);
        vm.expectRevert(AegisEscrow.NotOperator.selector);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, sig
        );
    }

    function test_recordSettlement_onlyOperator() public {
        _open(3, 0);
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400);
        vm.prank(operator);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, sig
        );
        vm.prank(stranger);
        vm.expectRevert(AegisEscrow.NotOperator.selector);
        escrow.recordSettlement(dealId, 1, 12_600_000, keccak256("rail"), false);
    }

    function test_resolveDispute_onlyOperator() public {
        _open(3, 0);
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.ESCALATE, 5100);
        vm.prank(operator);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.ESCALATE, 5100, sig
        );
        vm.prank(buyer);
        escrow.raiseDispute(dealId, 1);
        vm.prank(stranger);
        vm.expectRevert(AegisEscrow.NotOperator.selector);
        escrow.resolveDispute(dealId, 1, 100, 100, keccak256("decision"));
    }

    // ── double-anchor rejection ─────────────────────────────────────────────
    function test_doubleAnchor_reverts() public {
        _open(3, 0);
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400);
        vm.startPrank(operator);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, sig
        );
        vm.expectRevert(AegisEscrow.AlreadyAnchored.selector);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, sig
        );
        vm.stopPrank();
    }

    function test_openDeal_twice_reverts() public {
        _open(3, 0);
        vm.prank(operator);
        vm.expectRevert(AegisEscrow.DealExists.selector);
        escrow.openDeal(dealId, termsHash, buyer, seller, 3, 0);
    }

    // ── decision / confidence round trip ────────────────────────────────────
    function test_decisionAndConfidence_roundTrip() public {
        _open(3, 0);
        bytes memory sig = _sign(2, evidenceRoot, attestationHash, AegisEscrow.Decision.ESCALATE, 5100);
        vm.prank(operator);
        escrow.anchorAttestation(
            dealId, 2, evidenceRoot, attestationHash, AegisEscrow.Decision.ESCALATE, 5100, sig
        );
        AegisEscrow.MilestoneRecord memory record = escrow.getMilestone(dealId, 2);
        assertEq(uint8(record.decision), uint8(AegisEscrow.Decision.ESCALATE));
        assertEq(record.confidenceBps, 5100);
        assertEq(record.evidenceRoot, evidenceRoot);
        assertEq(record.attestationHash, attestationHash);
        assertEq(record.settledAmountPaise, 0, "escalate must not settle anything");
    }

    function test_confidenceAbove10000_reverts() public {
        _open(3, 0);
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 10_001);
        vm.prank(operator);
        vm.expectRevert(AegisEscrow.SeqOutOfRange.selector);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 10_001, sig
        );
    }

    // ── EIP-712 signature recovery ──────────────────────────────────────────
    function test_signatureRecovery_recordsAttestor() public {
        _open(3, 0);
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400);
        vm.prank(operator);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, sig
        );
        assertEq(escrow.getMilestone(dealId, 1).attestor, verifier);
    }

    function test_signatureOverAlteredPayload_recoversDifferentSigner() public {
        _open(3, 0);
        // Sign confidence 9400 but anchor 8000: the digest differs, so the
        // recovered address is not the verifier.
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400);
        vm.prank(operator);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 8000, sig
        );
        assertTrue(escrow.getMilestone(dealId, 1).attestor != verifier);
    }

    function test_malformedSignature_reverts() public {
        _open(3, 0);
        vm.prank(operator);
        vm.expectRevert(AegisEscrow.InvalidSignature.selector);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, hex"00"
        );
    }

    // ── dispute-window enforcement ──────────────────────────────────────────
    function test_disputeAfterWindow_reverts() public {
        uint64 ends = uint64(block.timestamp + 1 days);
        _open(3, ends);
        vm.warp(ends + 1);
        vm.prank(buyer);
        vm.expectRevert(AegisEscrow.DisputeWindowClosed.selector);
        escrow.raiseDispute(dealId, 1);
    }

    function test_disputeInsideWindow_succeeds() public {
        uint64 ends = uint64(block.timestamp + 7 days);
        _open(3, ends);
        vm.prank(seller);
        escrow.raiseDispute(dealId, 1);
        assertEq(uint8(escrow.getDeal(dealId).state), uint8(AegisEscrow.DealState.DISPUTED));
    }

    function test_disputeByStranger_reverts() public {
        _open(3, 0);
        vm.prank(stranger);
        vm.expectRevert(AegisEscrow.NotAParty.selector);
        escrow.raiseDispute(dealId, 1);
    }

    // ── settlement-amount bounds ────────────────────────────────────────────
    function test_settlementWithoutAnchor_reverts() public {
        _open(3, 0);
        vm.prank(operator);
        vm.expectRevert(AegisEscrow.NothingAnchored.selector);
        escrow.recordSettlement(dealId, 1, 12_600_000, keccak256("rail"), false);
    }

    function test_settlementOnEscalateWithoutHuman_reverts() public {
        _open(3, 0);
        bytes memory sig = _sign(2, evidenceRoot, attestationHash, AegisEscrow.Decision.ESCALATE, 5100);
        vm.startPrank(operator);
        escrow.anchorAttestation(
            dealId, 2, evidenceRoot, attestationHash, AegisEscrow.Decision.ESCALATE, 5100, sig
        );
        vm.expectRevert(AegisEscrow.DecisionIsNotRelease.selector);
        escrow.recordSettlement(dealId, 2, 16_800_000, keccak256("rail"), false);
        vm.stopPrank();
    }

    function test_settlementOnEscalateWithHuman_succeeds() public {
        _open(3, 0);
        bytes memory sig = _sign(2, evidenceRoot, attestationHash, AegisEscrow.Decision.ESCALATE, 5100);
        vm.startPrank(operator);
        escrow.anchorAttestation(
            dealId, 2, evidenceRoot, attestationHash, AegisEscrow.Decision.ESCALATE, 5100, sig
        );
        escrow.recordSettlement(dealId, 2, 16_800_000, keccak256("rail"), true);
        vm.stopPrank();
        AegisEscrow.MilestoneRecord memory record = escrow.getMilestone(dealId, 2);
        assertEq(record.settledAmountPaise, 16_800_000);
        assertTrue(record.humanApproved);
    }

    function test_doubleSettlement_reverts() public {
        _open(3, 0);
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400);
        vm.startPrank(operator);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, sig
        );
        escrow.recordSettlement(dealId, 1, 12_600_000, keccak256("rail"), false);
        vm.expectRevert(AegisEscrow.AlreadySettled.selector);
        escrow.recordSettlement(dealId, 1, 12_600_000, keccak256("rail"), false);
        vm.stopPrank();
    }

    function test_resolveDispute_splitRecorded() public {
        _open(3, uint64(block.timestamp + 7 days));
        bytes memory sig = _sign(3, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9100);
        vm.prank(operator);
        escrow.anchorAttestation(
            dealId, 3, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9100, sig
        );
        vm.prank(buyer);
        escrow.raiseDispute(dealId, 3);
        vm.prank(operator);
        escrow.resolveDispute(dealId, 3, 11_592_000, 1_008_000, keccak256("human-decision"));
        AegisEscrow.MilestoneRecord memory record = escrow.getMilestone(dealId, 3);
        assertEq(record.settledAmountPaise, 12_600_000);
        assertTrue(record.humanApproved);
        assertEq(uint8(escrow.getDeal(dealId).state), uint8(AegisEscrow.DealState.OPEN));
    }

    function test_resolveDispute_zeroSplit_reverts() public {
        _open(3, uint64(block.timestamp + 7 days));
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9100);
        vm.prank(operator);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9100, sig
        );
        vm.prank(buyer);
        escrow.raiseDispute(dealId, 1);
        vm.prank(operator);
        vm.expectRevert(AegisEscrow.SplitDoesNotBalance.selector);
        escrow.resolveDispute(dealId, 1, 0, 0, keccak256("decision"));
    }

    function test_seqOutOfRange_reverts() public {
        _open(3, 0);
        bytes memory sig = _sign(4, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400);
        vm.prank(operator);
        vm.expectRevert(AegisEscrow.SeqOutOfRange.selector);
        escrow.anchorAttestation(
            dealId, 4, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, sig
        );
    }

    function test_anchorOnUnknownDeal_reverts() public {
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400);
        vm.prank(operator);
        vm.expectRevert(AegisEscrow.DealNotOpen.selector);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, 9400, sig
        );
    }


    // ── cross-language EIP-712 agreement ────────────────────────────────────
    /// @dev These constants are computed independently in Python
    ///      (`backend/tests/unit/test_eip712_typehash.py`). If the Solidity type
    ///      string and the Python one ever drift apart, both tests fail, and an
    ///      attestation signed off-chain would stop recovering on-chain.
    function test_typeHashes_matchPython() public view {
        assertEq(
            keccak256(
                "Attestation(bytes32 dealId,uint8 seq,bytes32 evidenceRoot,bytes32 attestationHash,uint8 decision,uint16 confidenceBps)"
            ),
            0xb7141e326db1046201ae90cf14f4be36f2b2c770f9991b880b98dc0725e2d8bd
        );
        assertEq(
            keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
            0x8b73c3c69bb8fe3d512ecc4cf759cc79239f7b179b0ffacaa9a75d522b39400f
        );
        assertEq(keccak256("Aegis"), 0xe1e6dfd9a7c1491f4110b6be4afaea795c5a59bfeb2de99b858c0d497a8fa3a1);
        assertEq(keccak256("1"), 0xc89efdaa54c0f20c7adf612882df0950f5a951637e0307cdcb4c672f298b8bc6);
        assertEq(escrow.domainSeparator(), keccak256(abi.encode(
            0x8b73c3c69bb8fe3d512ecc4cf759cc79239f7b179b0ffacaa9a75d522b39400f,
            keccak256("Aegis"),
            keccak256("1"),
            block.chainid,
            address(escrow)
        )));
    }

    // ── fuzz: confidence round-trips for any valid value ────────────────────
    function testFuzz_confidenceRoundTrip(uint16 bps) public {
        bps = uint16(bound(uint256(bps), 0, 10_000));
        _open(1, 0);
        bytes memory sig = _sign(1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, bps);
        vm.prank(operator);
        escrow.anchorAttestation(
            dealId, 1, evidenceRoot, attestationHash, AegisEscrow.Decision.RELEASE, bps, sig
        );
        assertEq(escrow.getMilestone(dealId, 1).confidenceBps, bps);
        assertEq(escrow.getMilestone(dealId, 1).attestor, verifier);
    }
}
