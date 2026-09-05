// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title AegisEscrow
/// @notice Money never touches this contract. Rupees move on Razorpay the entire
///         time. The chain holds exactly two things: the rulebook of the deal, so
///         neither party can quietly edit it after the fact; and a fingerprint of
///         every AI decision, so "the AI decided" can be replaced with a
///         verifiable record.
/// @dev    Hashes, ids, integers, enums and signatures only (invariant I7). No
///         names, emails, addresses, documents, invoice contents, messages or raw
///         evidence can be passed to any function in this contract.
contract AegisEscrow {
    // ── Types ───────────────────────────────────────────────────────────────
    enum DealState {
        NONE,
        OPEN,
        DISPUTED,
        CLOSED
    }

    enum Decision {
        NONE,
        RELEASE,
        REJECT,
        ESCALATE
    }

    struct Deal {
        bytes32 termsHash;
        address buyer;
        address seller;
        uint64 disputeWindowEnds;
        uint8 milestoneCount;
        DealState state;
    }

    struct MilestoneRecord {
        bytes32 evidenceRoot; // merkle root of the evidence bundle
        bytes32 attestationHash; // sha256 of the canonical attestation JSON
        Decision decision;
        uint16 confidenceBps; // 0..10000
        uint64 settledAmountPaise;
        bytes32 railRef; // HASH of the rail reference, never the reference
        bool humanApproved;
        address attestor; // recovered from the EIP-712 signature
    }

    // ── Storage ─────────────────────────────────────────────────────────────
    address public immutable operator;

    mapping(bytes32 => Deal) public deals; // dealId
    mapping(bytes32 => MilestoneRecord) public milestones; // keccak(dealId, seq)
    mapping(bytes32 => uint64) public disputeRaisedAt; // keccak(dealId, seq)

    // ── EIP-712 ─────────────────────────────────────────────────────────────
    bytes32 private constant _EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant _ATTESTATION_TYPEHASH =
        keccak256(
            "Attestation(bytes32 dealId,uint8 seq,bytes32 evidenceRoot,bytes32 attestationHash,uint8 decision,uint16 confidenceBps)"
        );
    bytes32 private constant _NAME_HASH = keccak256("Aegis");
    bytes32 private constant _VERSION_HASH = keccak256("1");

    // ── Events ──────────────────────────────────────────────────────────────
    event DealOpened(bytes32 indexed dealId, bytes32 termsHash, uint8 milestoneCount);
    event AttestationAnchored(
        bytes32 indexed dealId,
        uint8 seq,
        bytes32 evidenceRoot,
        bytes32 attestationHash,
        Decision decision,
        uint16 confidenceBps,
        address attestor
    );
    event SettlementRecorded(
        bytes32 indexed dealId, uint8 seq, uint64 amountPaise, bytes32 railRef, bool humanApproved
    );
    event DisputeRaised(bytes32 indexed dealId, uint8 seq, address by);
    event DisputeResolved(
        bytes32 indexed dealId, uint8 seq, uint64 releasePaise, uint64 refundPaise, bytes32 decisionHash
    );

    // ── Errors ──────────────────────────────────────────────────────────────
    error NotOperator();
    error DealExists();
    error DealNotOpen();
    error SeqOutOfRange();
    error AlreadyAnchored();
    error AlreadySettled();
    error NothingAnchored();
    error DecisionIsNotRelease();
    error SettlementExceedsMilestone();
    error DisputeWindowClosed();
    error NotAParty();
    error NotDisputed();
    error SplitDoesNotBalance();
    error InvalidSignature();
    error ZeroTermsHash();
    error ZeroAttestationHash();
    error ZeroSettlementAmount();

    modifier onlyOperator() {
        if (msg.sender != operator) revert NotOperator();
        _;
    }

    constructor(address operator_) {
        operator = operator_ == address(0) ? msg.sender : operator_;
    }

    // ── Views ───────────────────────────────────────────────────────────────
    function milestoneKey(bytes32 dealId, uint8 seq) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(dealId, seq));
    }

    function getMilestone(bytes32 dealId, uint8 seq) external view returns (MilestoneRecord memory) {
        return milestones[milestoneKey(dealId, seq)];
    }

    function getDeal(bytes32 dealId) external view returns (Deal memory) {
        return deals[dealId];
    }

    function domainSeparator() public view returns (bytes32) {
        return keccak256(
            abi.encode(_EIP712_DOMAIN_TYPEHASH, _NAME_HASH, _VERSION_HASH, block.chainid, address(this))
        );
    }

    function attestationDigest(
        bytes32 dealId,
        uint8 seq,
        bytes32 evidenceRoot,
        bytes32 attestationHash,
        Decision decision,
        uint16 confidenceBps
    ) public view returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                _ATTESTATION_TYPEHASH,
                dealId,
                seq,
                evidenceRoot,
                attestationHash,
                uint8(decision),
                confidenceBps
            )
        );
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator(), structHash));
    }

    // ── Writes ──────────────────────────────────────────────────────────────
    function openDeal(
        bytes32 dealId,
        bytes32 termsHash,
        address buyer,
        address seller,
        uint8 milestoneCount,
        uint64 disputeWindowEnds
    ) external onlyOperator {
        if (deals[dealId].state != DealState.NONE) revert DealExists();
        if (termsHash == bytes32(0)) revert ZeroTermsHash();
        if (milestoneCount == 0) revert SeqOutOfRange();
        deals[dealId] = Deal({
            termsHash: termsHash,
            buyer: buyer,
            seller: seller,
            disputeWindowEnds: disputeWindowEnds,
            milestoneCount: milestoneCount,
            state: DealState.OPEN
        });
        emit DealOpened(dealId, termsHash, milestoneCount);
    }

    /// @notice Anchors one AI decision. The signer is recovered on chain, so the
    ///         record proves *who* attested -- not merely that something was attested.
    function anchorAttestation(
        bytes32 dealId,
        uint8 seq,
        bytes32 evidenceRoot,
        bytes32 attestationHash,
        Decision decision,
        uint16 confidenceBps,
        bytes calldata verifierSig
    ) external onlyOperator {
        Deal storage deal = deals[dealId];
        if (deal.state != DealState.OPEN && deal.state != DealState.DISPUTED) revert DealNotOpen();
        if (seq == 0 || seq > deal.milestoneCount) revert SeqOutOfRange();
        if (confidenceBps > 10_000) revert SeqOutOfRange();
        // Zero is the "nothing anchored" sentinel read here and by
        // recordSettlement.  Accepting one would leave the record still reading
        // as unanchored, so the same milestone could be anchored a second time
        // with a different decision and a different attestor.
        if (attestationHash == bytes32(0)) revert ZeroAttestationHash();

        bytes32 key = milestoneKey(dealId, seq);
        if (milestones[key].attestationHash != bytes32(0)) revert AlreadyAnchored();

        address attestor = _recover(
            attestationDigest(dealId, seq, evidenceRoot, attestationHash, decision, confidenceBps),
            verifierSig
        );
        if (attestor == address(0)) revert InvalidSignature();

        MilestoneRecord storage record = milestones[key];
        record.evidenceRoot = evidenceRoot;
        record.attestationHash = attestationHash;
        record.decision = decision;
        record.confidenceBps = confidenceBps;
        record.attestor = attestor;

        emit AttestationAnchored(
            dealId, seq, evidenceRoot, attestationHash, decision, confidenceBps, attestor
        );
    }

    function recordSettlement(
        bytes32 dealId,
        uint8 seq,
        uint64 amountPaise,
        bytes32 railRef,
        bool humanApproved
    ) external onlyOperator {
        Deal storage deal = deals[dealId];
        if (deal.state == DealState.NONE) revert DealNotOpen();
        if (seq == 0 || seq > deal.milestoneCount) revert SeqOutOfRange();

        // Zero is the "not settled" sentinel guarding the line below, so a
        // zero-amount settlement would record itself and still read as unsettled
        // -- the milestone could then be settled again and its rail reference
        // overwritten.  No real payout is zero paise.
        if (amountPaise == 0) revert ZeroSettlementAmount();

        bytes32 key = milestoneKey(dealId, seq);
        MilestoneRecord storage record = milestones[key];
        if (record.attestationHash == bytes32(0)) revert NothingAnchored();
        if (record.settledAmountPaise != 0) revert AlreadySettled();
        // A RELEASE decision, or a human on the record. Never neither.
        if (record.decision != Decision.RELEASE && !humanApproved) revert DecisionIsNotRelease();

        record.settledAmountPaise = amountPaise;
        record.railRef = railRef;
        record.humanApproved = humanApproved;

        emit SettlementRecorded(dealId, seq, amountPaise, railRef, humanApproved);
    }

    function raiseDispute(bytes32 dealId, uint8 seq) external {
        Deal storage deal = deals[dealId];
        if (deal.state == DealState.NONE || deal.state == DealState.CLOSED) revert DealNotOpen();
        if (seq == 0 || seq > deal.milestoneCount) revert SeqOutOfRange();
        if (msg.sender != deal.buyer && msg.sender != deal.seller && msg.sender != operator) {
            revert NotAParty();
        }
        if (deal.disputeWindowEnds != 0 && block.timestamp > deal.disputeWindowEnds) {
            revert DisputeWindowClosed();
        }
        deal.state = DealState.DISPUTED;
        disputeRaisedAt[milestoneKey(dealId, seq)] = uint64(block.timestamp);
        emit DisputeRaised(dealId, seq, msg.sender);
    }

    function resolveDispute(
        bytes32 dealId,
        uint8 seq,
        uint64 releasePaise,
        uint64 refundPaise,
        bytes32 decisionHash
    ) external onlyOperator {
        Deal storage deal = deals[dealId];
        if (deal.state != DealState.DISPUTED) revert NotDisputed();
        if (seq == 0 || seq > deal.milestoneCount) revert SeqOutOfRange();

        bytes32 key = milestoneKey(dealId, seq);
        // `deal.state` is per deal but a dispute is raised per milestone.  Without
        // this check a dispute on milestone 1 unlocked resolveDispute for every
        // other milestone of the deal -- and resolveDispute writes
        // settledAmountPaise and humanApproved directly, so a REJECT or an
        // ESCALATE could be settled without ever meeting recordSettlement's
        // "a RELEASE, or a human on the record" requirement.
        if (disputeRaisedAt[key] == 0) revert NotDisputed();
        MilestoneRecord storage record = milestones[key];
        if (record.attestationHash == bytes32(0)) revert NothingAnchored();

        uint64 total = releasePaise + refundPaise;
        if (total == 0) revert SplitDoesNotBalance();
        if (record.settledAmountPaise != 0 && total > record.settledAmountPaise) {
            revert SettlementExceedsMilestone();
        }

        record.settledAmountPaise = total;
        record.humanApproved = true;
        // This milestone's dispute is over; re-opening it needs a new
        // raiseDispute.  Otherwise a later dispute on any sibling milestone would
        // let this one be resolved a second time.
        disputeRaisedAt[key] = 0;
        deal.state = DealState.OPEN;

        emit DisputeResolved(dealId, seq, releasePaise, refundPaise, decisionHash);
    }

    function closeDeal(bytes32 dealId) external onlyOperator {
        Deal storage deal = deals[dealId];
        if (deal.state != DealState.OPEN) revert DealNotOpen();
        deal.state = DealState.CLOSED;
    }

    // ── Signature recovery ──────────────────────────────────────────────────
    function _recover(bytes32 digest, bytes calldata signature) private pure returns (address) {
        if (signature.length != 65) return address(0);
        bytes32 r;
        bytes32 s;
        uint8 v;
        // solhint-disable-next-line no-inline-assembly
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (v < 27) v += 27;
        if (v != 27 && v != 28) return address(0);
        // Reject the upper half of the curve order (malleable signatures).
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            return address(0);
        }
        return ecrecover(digest, v, r, s);
    }
}
