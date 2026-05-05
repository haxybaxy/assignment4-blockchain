// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {ERC721Enumerable} from "@openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";
import {ERC721URIStorage} from "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";

/// @title  EventTickets721
/// @notice ERC-721 event tickets. The owner creates events with a face value
///         and supply cap; users mint primary-sale tickets by paying ETH;
///         tickets can be transferred for free using standard ERC-721 calls
///         or listed for resale through this contract with a 2× price cap
///         and a 2% protocol fee retained for the owner.
///
/// @dev    Replaces Assignment 3's custom struct/mapping ticket model with the
///         ERC-721 standard. The benefit is interoperability (any wallet,
///         marketplace, or block explorer that understands NFTs can read these
///         tickets without custom integration) and a battle-tested ownership
///         implementation. The cost is per-mint storage gas, which we accept.
///
///         Metadata split:
///           - On-chain (this contract): eventId, seatNumber, originalPrice
///             per token. These are needed by contract logic (resale cap,
///             refund math, display).
///           - Off-chain (`tokenURI`): everything human-facing — date, venue,
///             image, attributes — served as JSON behind a URI per token.
///             For the demo, the Flask app serves these from
///             `app/static/metadata/<id>.json`. In production we'd pin them
///             to IPFS for immutability.
contract EventTickets721 is ERC721, ERC721Enumerable, ERC721URIStorage, Ownable {
    using Strings for uint256;

    struct EventInfo {
        string name;
        uint256 pricePerTicket;
        uint256 maxSupply;
        uint256 sold;
        bool active;
        bool exists;
        string baseURI; // tokenURI for ticket #N is `baseURI + N.json`
    }

    // ---------- Storage ----------

    uint256 public eventCount;
    mapping(uint256 => EventInfo) private _events;

    /// @dev tokenIds are sequential and global across all events.
    uint256 private _nextTokenId;

    /// @notice tokenId → eventId
    mapping(uint256 => uint256) public ticketEventOf;

    /// @notice tokenId → original face-value price (basis for the 2× resale cap).
    mapping(uint256 => uint256) public originalPriceOf;

    /// @notice tokenId → seat number within its event (1-indexed).
    mapping(uint256 => uint256) public seatNumberOf;

    /// @notice tokenId → resale listing price; 0 means not listed.
    mapping(uint256 => uint256) public listingPrice;

    /// @notice 200 bps = 2 %. Kept by the contract; owner withdraws.
    uint256 public constant RESALE_FEE_BPS = 200;
    uint256 public constant RESALE_FEE_DENOM = 10_000;

    /// @notice Resale price ≤ originalPrice × this.
    uint256 public constant MAX_RESALE_MULTIPLIER = 2;

    // ---------- Events ----------

    event EventCreated(
        uint256 indexed eventId,
        string name,
        uint256 pricePerTicket,
        uint256 maxSupply,
        string baseURI
    );
    event EventStatusChanged(uint256 indexed eventId, bool active);
    event TicketMinted(
        uint256 indexed tokenId,
        uint256 indexed eventId,
        address indexed buyer,
        uint256 seatNumber,
        uint256 pricePaid
    );
    event TicketListed(uint256 indexed tokenId, address indexed seller, uint256 price);
    event TicketUnlisted(uint256 indexed tokenId, address indexed seller);
    event TicketResold(
        uint256 indexed tokenId,
        address indexed seller,
        address indexed buyer,
        uint256 price,
        uint256 sellerProceeds,
        uint256 protocolFee
    );
    event Withdrawn(address indexed to, uint256 amount);

    // ---------- Errors ----------

    error EmptyName();
    error ZeroPrice();
    error ZeroSupply();
    error EmptyBaseURI();
    error EventNotFound(uint256 eventId);
    error EventInactive(uint256 eventId);
    error SoldOut(uint256 eventId);
    error IncorrectPayment(uint256 required, uint256 provided);
    error NotTicketOwner(uint256 tokenId, address caller);
    error AlreadyListed(uint256 tokenId);
    error NotListed(uint256 tokenId);
    error NotApproved(uint256 tokenId);
    error PriceTooHigh(uint256 requested, uint256 max);
    error CannotBuyOwnTicket();
    error NothingToWithdraw();
    error TransferFailed();

    // ---------- Constructor ----------

    constructor() ERC721("Event Ticket", "TIX") Ownable(msg.sender) {}

    // ---------- Admin ----------

    /// @notice Create a new event. `baseURI` should end with a slash; the
    ///         contract appends `<tokenId>.json` to construct each ticket's URI.
    function createEvent(
        string calldata name,
        uint256 pricePerTicket,
        uint256 maxSupply,
        string calldata baseURI
    ) external onlyOwner returns (uint256 eventId) {
        if (bytes(name).length == 0) revert EmptyName();
        if (pricePerTicket == 0) revert ZeroPrice();
        if (maxSupply == 0) revert ZeroSupply();
        if (bytes(baseURI).length == 0) revert EmptyBaseURI();

        eventId = eventCount;
        _events[eventId] = EventInfo({
            name: name,
            pricePerTicket: pricePerTicket,
            maxSupply: maxSupply,
            sold: 0,
            active: true,
            exists: true,
            baseURI: baseURI
        });
        eventCount += 1;
        emit EventCreated(eventId, name, pricePerTicket, maxSupply, baseURI);
    }

    /// @notice Pause / resume primary sales for an event.
    function setEventActive(uint256 eventId, bool active) external onlyOwner {
        EventInfo storage e = _requireEvent(eventId);
        e.active = active;
        emit EventStatusChanged(eventId, active);
    }

    /// @notice Withdraw protocol fees (and any stray ETH) to the owner.
    function withdraw() external onlyOwner {
        uint256 bal = address(this).balance;
        if (bal == 0) revert NothingToWithdraw();
        (bool ok, ) = payable(owner()).call{value: bal}("");
        if (!ok) revert TransferFailed();
        emit Withdrawn(owner(), bal);
    }

    // ---------- Primary sale ----------

    /// @notice Mint one primary-sale ticket NFT for `eventId`. Excess ETH
    ///         is refunded.
    function buyTicket(uint256 eventId) external payable returns (uint256 tokenId) {
        EventInfo storage e = _requireEvent(eventId);
        if (!e.active) revert EventInactive(eventId);
        if (e.sold >= e.maxSupply) revert SoldOut(eventId);
        if (msg.value < e.pricePerTicket) revert IncorrectPayment(e.pricePerTicket, msg.value);

        // Effects
        tokenId = _nextTokenId++;
        uint256 seat = e.sold + 1;
        e.sold += 1;
        ticketEventOf[tokenId] = eventId;
        originalPriceOf[tokenId] = e.pricePerTicket;
        seatNumberOf[tokenId] = seat;

        _safeMint(msg.sender, tokenId);
        _setTokenURI(tokenId, string.concat(e.baseURI, tokenId.toString(), ".json"));

        emit TicketMinted(tokenId, eventId, msg.sender, seat, e.pricePerTicket);

        // Interaction: refund overpay
        uint256 excess = msg.value - e.pricePerTicket;
        if (excess > 0) {
            (bool ok, ) = payable(msg.sender).call{value: excess}("");
            if (!ok) revert TransferFailed();
        }
    }

    // ---------- Resale marketplace ----------

    /// @notice List `tokenId` for resale at `price` wei.
    /// @dev    Caller must (a) own the token and (b) have approved this
    ///         contract for that token (or for all of their tokens) so that
    ///         `transferFrom` succeeds when a buyer arrives.
    function listForResale(uint256 tokenId, uint256 price) external {
        if (price == 0) revert ZeroPrice();
        address ticketOwner = ownerOf(tokenId); // reverts if token doesn't exist
        if (ticketOwner != msg.sender) revert NotTicketOwner(tokenId, msg.sender);
        if (listingPrice[tokenId] != 0) revert AlreadyListed(tokenId);

        // Demonstrating the standard ERC-721 approval pattern explicitly: the
        // marketplace contract refuses to list unless it can move the token.
        if (
            getApproved(tokenId) != address(this) &&
            !isApprovedForAll(ticketOwner, address(this))
        ) revert NotApproved(tokenId);

        uint256 cap = originalPriceOf[tokenId] * MAX_RESALE_MULTIPLIER;
        if (price > cap) revert PriceTooHigh(price, cap);

        listingPrice[tokenId] = price;
        emit TicketListed(tokenId, ticketOwner, price);
    }

    /// @notice Remove a listing. Only callable by the current owner.
    function cancelResale(uint256 tokenId) external {
        if (listingPrice[tokenId] == 0) revert NotListed(tokenId);
        address ticketOwner = ownerOf(tokenId);
        if (ticketOwner != msg.sender) revert NotTicketOwner(tokenId, msg.sender);
        listingPrice[tokenId] = 0;
        emit TicketUnlisted(tokenId, ticketOwner);
    }

    /// @notice Buy a listed ticket. Pays seller (price − 2 %), keeps the fee,
    ///         refunds any overpayment, and transfers the NFT via the
    ///         standard ERC-721 `transferFrom` (so the approval pattern is
    ///         what actually moves ownership).
    function buyResale(uint256 tokenId) external payable {
        uint256 price = listingPrice[tokenId];
        if (price == 0) revert NotListed(tokenId);
        if (msg.value < price) revert IncorrectPayment(price, msg.value);

        address seller = ownerOf(tokenId);
        if (seller == msg.sender) revert CannotBuyOwnTicket();

        uint256 fee = (price * RESALE_FEE_BPS) / RESALE_FEE_DENOM;
        uint256 proceeds = price - fee;

        // Effects: clear listing first to make reentrancy via fallback harmless.
        listingPrice[tokenId] = 0;

        emit TicketResold(tokenId, seller, msg.sender, price, proceeds, fee);

        // Interaction A: move the NFT using the *standard* ERC-721 pathway.
        // The seller approved address(this) earlier, so transferFrom succeeds.
        this.transferFrom(seller, msg.sender, tokenId);

        // Interaction B: pay seller their proceeds.
        (bool okSeller, ) = payable(seller).call{value: proceeds}("");
        if (!okSeller) revert TransferFailed();

        // Interaction C: refund any overpayment.
        uint256 excess = msg.value - price;
        if (excess > 0) {
            (bool okRefund, ) = payable(msg.sender).call{value: excess}("");
            if (!okRefund) revert TransferFailed();
        }
        // Protocol fee remains in contract balance for the owner to withdraw.
    }

    // ---------- Views ----------

    /// @notice Returns the events catalogue.
    function getAllEvents()
        external
        view
        returns (
            uint256[] memory ids,
            string[] memory names,
            uint256[] memory prices,
            uint256[] memory supplies,
            uint256[] memory solds,
            bool[] memory actives
        )
    {
        uint256 n = eventCount;
        ids = new uint256[](n);
        names = new string[](n);
        prices = new uint256[](n);
        supplies = new uint256[](n);
        solds = new uint256[](n);
        actives = new bool[](n);
        for (uint256 i = 0; i < n; i++) {
            EventInfo storage e = _events[i];
            ids[i] = i;
            names[i] = e.name;
            prices[i] = e.pricePerTicket;
            supplies[i] = e.maxSupply;
            solds[i] = e.sold;
            actives[i] = e.active;
        }
    }

    /// @notice Single-event read.
    function getEvent(uint256 eventId)
        external
        view
        returns (
            string memory name,
            uint256 pricePerTicket,
            uint256 maxSupply,
            uint256 sold,
            bool active,
            string memory baseURI
        )
    {
        EventInfo storage e = _requireEvent(eventId);
        return (e.name, e.pricePerTicket, e.maxSupply, e.sold, e.active, e.baseURI);
    }

    /// @notice Convenience read: every token id currently listed for resale.
    function listedTickets() external view returns (uint256[] memory) {
        uint256 total = totalSupply();
        uint256 count;
        for (uint256 i = 0; i < total; i++) {
            uint256 id = tokenByIndex(i);
            if (listingPrice[id] != 0) count++;
        }
        uint256[] memory out = new uint256[](count);
        uint256 k;
        for (uint256 i = 0; i < total; i++) {
            uint256 id = tokenByIndex(i);
            if (listingPrice[id] != 0) {
                out[k++] = id;
            }
        }
        return out;
    }

    // ---------- Required overrides (ERC721 + Enumerable + URIStorage) ----------

    /// @dev OZ v5 funnels every transfer (mint, burn, transfer) through `_update`.
    ///      We override to (1) chain Enumerable's bookkeeping and (2) clear any
    ///      stale resale listing if the token is moved without going through
    ///      `buyResale` (e.g. a free transferFrom). This keeps marketplace
    ///      state coherent with on-chain reality.
    function _update(address to, uint256 tokenId, address auth)
        internal
        override(ERC721, ERC721Enumerable)
        returns (address)
    {
        address from = _ownerOf(tokenId);
        if (from != address(0) && from != to && listingPrice[tokenId] != 0) {
            // Tickets that change hands outside the marketplace flow get
            // unlisted automatically — the buyer wouldn't honour the old listing.
            listingPrice[tokenId] = 0;
            emit TicketUnlisted(tokenId, from);
        }
        return super._update(to, tokenId, auth);
    }

    function _increaseBalance(address account, uint128 value)
        internal
        override(ERC721, ERC721Enumerable)
    {
        super._increaseBalance(account, value);
    }

    function tokenURI(uint256 tokenId)
        public
        view
        override(ERC721, ERC721URIStorage)
        returns (string memory)
    {
        return super.tokenURI(tokenId);
    }

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, ERC721Enumerable, ERC721URIStorage)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    // ---------- Internals ----------

    function _requireEvent(uint256 eventId) private view returns (EventInfo storage e) {
        e = _events[eventId];
        if (!e.exists) revert EventNotFound(eventId);
    }
}
