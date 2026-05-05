// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/// @title LoyaltyPoints
/// @notice Owner-issued, user-transferable loyalty points implemented as ERC-20.
///         The deployer (the "business") is the only address that can mint
///         new points; holders can transfer them to any other address using
///         the standard ERC-20 transfer/approve flow.
/// @dev    Design notes:
///         - Decimals overridden to 0. Points are integer awards ("you got 50
///           points for buying coffee"); fractional points are nonsensical for
///           this use case and would just confuse the UI.
///         - We deliberately do NOT add Pausable, Burnable, or a hard cap.
///           They're easy to slot in later — keeping the surface small is the
///           point of the exercise. README documents the trade-offs.
///         - The ERC-20 base contract already emits Transfer(0x0, to, amount)
///           on mint, which is the canonical signal indexers expect. We add
///           a separate `LoyaltyMinted` event so listeners that only care
///           about issuance can filter without cross-referencing transfer
///           sources.
contract LoyaltyPoints is ERC20, Ownable {
    /// @notice Emitted whenever the owner mints new points to a customer.
    event LoyaltyMinted(address indexed to, uint256 amount);

    error ZeroAmount();

    /// @notice Deploys the token. The deployer becomes the owner / minter.
    constructor() ERC20("Loyalty Points", "LOYAL") Ownable(msg.sender) {}

    /// @notice Whole-unit points; fractions don't make sense here.
    function decimals() public pure override returns (uint8) {
        return 0;
    }

    /// @notice Owner-only mint. `to == 0x0` is rejected by `_mint` already;
    ///         we add an explicit zero-amount guard so accidental no-ops fail
    ///         loudly instead of emitting empty events.
    function mint(address to, uint256 amount) external onlyOwner {
        if (amount == 0) revert ZeroAmount();
        _mint(to, amount);
        emit LoyaltyMinted(to, amount);
    }
}
