// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";
import {AegisEscrow} from "../src/AegisEscrow.sol";

/// @notice `forge script script/Deploy.s.sol --rpc-url base_sepolia --broadcast`
///         The deployer becomes the operator unless AEGIS_OPERATOR is set.
contract Deploy is Script {
    function run() external returns (address deployed) {
        uint256 pk = vm.envUint("OPERATOR_PRIVATE_KEY");
        address operator = vm.envOr("AEGIS_OPERATOR", vm.addr(pk));
        vm.startBroadcast(pk);
        AegisEscrow escrow = new AegisEscrow(operator);
        vm.stopBroadcast();
        deployed = address(escrow);
        console2.log("AegisEscrow deployed at", deployed);
        console2.log("operator", operator);
    }
}
