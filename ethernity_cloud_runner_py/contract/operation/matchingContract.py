from collections import namedtuple
from typing import Any, Dict, List, Optional

from web3 import Web3

from ..abi.matchingAbi import (image_registry as image_registry_abi, matching as matching_abi, pox as pox_abi,
                               pox_1_2 as pox_1_2_abi, pricing as pricing_abi, reader as reader_abi,
                               session_registry as session_registry_abi)
from ...errors import call_refused
from ...matching import KIND_DEFAULT_RELEASE, UINT32_MAX, ImageRecords, Template, decode_template, template_key

# The PoX generations that take addDORequestV2, by their VERSION() answer, and
# the ABI of each one's add: "2.0" with maxGflops uint48 (the minimum EPC in
# bits 32 to 47), "1.2" with maxGflops uint32 (MATCHING-SYNC-PLAN.md 3.9).
V2_ADD_ABI = {"2.0": pox_abi, "1.2": pox_1_2_abi}
ZERO_ADDRESS = "0x" + "00" * 20

# What a network's PoX answers before a request (OD18): `version`, its
# VERSION() answer (None when it has none), and `matching_address`, the
# PoxMatching its pricing names (pricingAddress(), then the pricing's
# matching()), the zero address when it names none.
PoxGeneration = namedtuple("PoxGeneration", "version matching_address")
NO_GENERATION = PoxGeneration(None, ZERO_ADDRESS)


def _refused_as(read: Any, refused: Any) -> Any:
    """`read()`, or `refused` when the contract refuses the call
    (errors.call_refused); any other failure is raised."""
    try:
        return read()
    except Exception as e:
        if call_refused(e):
            return refused
        raise


def read_generation(contract: Any) -> PoxGeneration:
    """The PoxGeneration of the PoX at `contract`'s protocol address, read on
    its provider: VERSION(), and for a PoX whose answer takes addDORequestV2
    (V2_ADD_ABI) its pricing's matching(). A read the contract refuses is
    an answer (no version, no PoxMatching); a read the RPC does not answer
    is raised."""
    w3 = contract.provider
    pox = w3.eth.contract(address=Web3.to_checksum_address(contract.protocol_address), abi=pox_abi)
    version = _refused_as(lambda: pox.functions.VERSION().call(), None)
    if version not in V2_ADD_ABI:
        return PoxGeneration(version, ZERO_ADDRESS)
    pricing_address = _refused_as(lambda: pox.functions.pricingAddress().call(), ZERO_ADDRESS)
    if int(pricing_address, 16) == 0:
        return PoxGeneration(version, ZERO_ADDRESS)
    pricing = w3.eth.contract(address=Web3.to_checksum_address(pricing_address), abi=pricing_abi)
    return PoxGeneration(version, _refused_as(lambda: pricing.functions.matching().call(), ZERO_ADDRESS))


def send_v2_add(contract: Any, version: str, resources: Dict[str, int], bid_wei: int, max_gflops: int,
                relays_per_hour: int, gas_level: int, metadata: List[str]) -> str:
    """addDORequestV2 in the form of the PoX's VERSION() (V2_ADD_ABI) with
    the resources of `resources`, one instance, the bid per CU-hour, the
    maxGflops argument, the chain fee's relays per hour and gas level, and
    the four metadata strings, made as a call from the runner's wallet
    first and sent through `contract`'s _build_sign_send when the call
    passes. The "1.2" form carries the low 32 bits of `max_gflops`, which
    hold no minimum EPC."""
    word = int(max_gflops) if version == "2.0" else int(max_gflops) & UINT32_MAX
    pox = contract.provider.eth.contract(address=Web3.to_checksum_address(contract.protocol_address),
                                         abi=V2_ADD_ABI[version])
    fn = pox.functions.addDORequestV2(
        resources["cpu"], resources["memory"], resources["storage"], resources["bandwidth"],
        resources["duration"], 1, int(bid_wei), word, int(relays_per_hour), int(gas_level), *metadata)
    fn.call({"from": contract.signer.address})
    return contract._build_sign_send(fn, GAS_FLOOR["addDORequestV2"])

# The roll entries one paged read of the reader asks for (`count` of
# candidates, bidQuote, bidQuoteFor and tierScore) where the network entry
# names no MATCH_PAGE_ENTRIES: bloxberg's page, the smallest of the callers'
# pages (spec/matching.md section 2: 650 on bloxberg, 800 on Polygon and
# Amoy, 1,450 on LitVM).
DEFAULT_PAGE_ENTRIES = 650
# The claimers one claimersOf call reads.
CLAIMERS_PAGE = 100

# The gas each send is built with at least; build_transaction asks the node
# for the call's estimate and _build_sign_send takes the larger.
GAS_FLOOR = {
    "addDORequestV2": 1_500_000,
    "_placeOrder": 1_500_000,
    "increaseBid": 600_000,
    "expireUnstarted": 600_000,
    "expireOrder": 600_000,
    "noteRefund": 300_000,
    "noteAmbiguous": 600_000,
}


def _outputs(abi: List[dict], name: str) -> List[str]:
    """The names of the outputs of function `name` of `abi`, in order; of the
    components of a function answering one struct."""
    outputs = next(e for e in abi if e.get("name") == name)["outputs"]
    if len(outputs) == 1 and "components" in outputs[0]:
        outputs = outputs[0]["components"]
    return [o["name"] for o in outputs]


class MatchingContracts:
    """The PoX 2.0 contracts of a network with matching, as a runner reads
    and sends to them (MATCHING-DESIGN.md section 8): the PoX at the
    protocol contract's address, whose VERSION() answer `version` names the
    form of its V2 add (V2_ADD_ABI), PoxMatching at the address the PoX's
    pricing names (read_generation) and PoxMatchReader at the address
    PoxMatching's reader() answers (bind_reader), all on the protocol
    contract's provider. Every transaction is first made as a call from the
    runner's wallet, and sent through the protocol contract's
    _build_sign_send only when the call passes; a call that reverts raises
    what the provider raised and nothing is sent."""

    def __init__(self, contract: Any, matching_address: str, page_entries: Optional[int] = None,
                 version: str = "2.0") -> None:
        self.contract = contract
        w3 = contract.provider
        self.w3 = w3
        self.version = version
        self.pox = w3.eth.contract(address=Web3.to_checksum_address(contract.protocol_address), abi=pox_abi)
        self.matching = w3.eth.contract(address=Web3.to_checksum_address(matching_address), abi=matching_abi)
        self.reader: Any = None
        self.page_entries = int(page_entries or DEFAULT_PAGE_ENTRIES)

    def bind_reader(self) -> str:
        """Binds the PoxMatchReader PoxMatching names (reader(), written once
        by its owner) and returns its address. Raises ValueError while
        PoxMatching names none."""
        address = self.matching.functions.reader().call()
        if int(address, 16) == 0:
            raise ValueError(f"PoxMatching {self.matching.address} names no PoxMatchReader (reader() is zero): a "
                             "request cannot be served by claims on this network yet, and none is sent.")
        self.reader = self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=reader_abi)
        return address

    # ------------------------------------------------------------- sends

    def _send(self, contract_fn: Any, name: str) -> str:
        contract_fn.call({"from": self.contract.signer.address})
        return self.contract._build_sign_send(contract_fn, GAS_FLOOR[name])

    def add_do_request_v2(self, resources: Dict[str, int], bid_wei: int, max_gflops: int, relays_per_hour: int,
                          gas_level: int, metadata: List[str]) -> str:
        """addDORequestV2 in the PoX's form (send_v2_add) with the resources
        of `resources`, one instance, the bid per CU-hour, the maxGflops
        argument (the minimum EPC, the required GFLOPS and the ceiling), the
        chain fee's relays per hour and gas level, and the four metadata
        strings."""
        return send_v2_add(self.contract, self.version, resources, bid_wei, max_gflops, relays_per_hour, gas_level,
                           metadata)

    def place_order(self, do_request_id: int, dp_request_id: int) -> str:
        """The approval of a claim: _placeOrder from the data owner on the
        claim's offer (3.10)."""
        return self._send(self.pox.functions._placeOrder(int(do_request_id), int(dp_request_id)), "_placeOrder")

    def increase_bid(self, do_request_id: int, bid_wei: int) -> str:
        return self._send(self.pox.functions.increaseBid(int(do_request_id), int(bid_wei)), "increaseBid")

    def expire_unstarted(self, order_id: int) -> str:
        return self._send(self.pox.functions.expireUnstarted(int(order_id)), "expireUnstarted")

    def expire_order(self, order_id: int) -> str:
        return self._send(self.pox.functions.expireOrder(int(order_id)), "expireOrder")

    def note_refund(self, order_id: int) -> str:
        return self._send(self.matching.functions.noteRefund(int(order_id)), "noteRefund")

    def note_ambiguous(self, order_id: int, hints: List[int]) -> str:
        return self._send(self.matching.functions.noteAmbiguous(int(order_id), [int(h) for h in hints]),
                          "noteAmbiguous")

    def placed_order(self, receipt: Any) -> Optional[int]:
        """The order id the _orderPlacedEV of a mined approval names."""
        for log in receipt["logs"]:
            if log["address"].lower() != self.pox.address.lower():
                continue
            try:
                event = self.pox.events._orderPlacedEV().process_log(log)
            except Exception:
                continue
            return int(event["args"]["_orderNumber"])
        return None

    # ------------------------------------------------------------- reads

    def claims_on(self) -> bool:
        return bool(self.matching.functions.claimsOn().call())

    def minimum_on(self) -> bool:
        return bool(self.matching.functions.minimumOn().call())

    def slot_seconds(self) -> int:
        return int(self.matching.functions.slotSeconds().call())

    def node_standing(self, node: str) -> tuple:
        """(score, beatAgeSlots, bannedUntil) of `node`."""
        return tuple(self.matching.functions.nodeStanding(Web3.to_checksum_address(node)).call())

    def last_failure_slot(self, node: str) -> int:
        return int(self.matching.functions.recordOf(Web3.to_checksum_address(node)).call()[6])

    def image_health(self, image: bytes) -> tuple:
        """(s7, f7, nodes, owners, marked) of the image key `image`."""
        return tuple(self.matching.functions.imageHealth(bytes(image)).call())

    def health_words(self, image: bytes) -> List[int]:
        return [int(w) for w in self.matching.functions.healthOf(bytes(image)).call()]

    def template(self, name: str) -> Template:
        word, _provider = self.matching.functions.templateOf(template_key(name)).call()
        return decode_template(word)

    def parameter_set(self, index: int) -> Dict[str, int]:
        """PoxMatching's parameter set `index`, by field name."""
        values = self.matching.functions.parameterSet(int(index)).call()
        return dict(zip(_outputs(matching_abi, "parameterSet"), values))

    def early33(self, order_id: int) -> bool:
        """Whether a code 33 in the order's stored result is a timeout before
        its time on its template's constants, as PoxMatching judges it."""
        return bool(self.matching.functions.early33(int(order_id)).call())

    def request_info(self, do_request_id: int) -> Dict[str, Any]:
        """requestInfo by field name; `parameterSet` is the index of the set
        the request takes, NO_PARAMETER_SET (256) when none is in force."""
        values = self.reader.functions.requestInfo(int(do_request_id)).call()
        return dict(zip(_outputs(reader_abi, "requestInfo"), values))

    def can_claim_of(self, do_request_id: int, nodes: List[str]) -> tuple:
        """(roundStamp, canClaim) of `nodes` at the request's current round:
        whether each can still claim it, as scheduleOf's canClaim answers it
        for the mandated nodes."""
        stamp, flags = self.reader.functions.canClaimOf(
            int(do_request_id), [Web3.to_checksum_address(n) for n in nodes]).call()
        return bytes(stamp), [bool(f) for f in flags]

    def escrow_for(self, hours: int, bid_wei: int, max_gflops: int, relays_per_hour: int, gas_level: int,
                   metadata1: str) -> Dict[str, int]:
        """What addDORequestV2 pulls for these terms in the latest block, by
        field name: escrowWei, its work part workWei at escrowGflops,
        chainFeeWei, and the publishers' fee percents trustedZoneFee and
        secureLockFee that `metadata1` (fields 1 and 2) carries."""
        values = self.reader.functions.escrowFor(int(hours), int(bid_wei), int(max_gflops), int(relays_per_hour),
                                                 int(gas_level), metadata1).call()
        return {name: int(value) for name, value in zip(_outputs(reader_abi, "escrowFor"), values)}

    def candidate_pages(self, do_request_id: int, round_number: int, beyond: bool = False,
                        start: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """The `candidates` pages of one read of round `round_number`: from the
        top of the roll, or with `beyond` set on from the last page of
        `start`, a read without it, to the roll's end; each page a mapping of
        the view's answers. A read without `beyond` ends at the end of the
        stop band."""
        names = _outputs(reader_abi, "candidates")
        band, index, h, found = 49, 0, b"\x00" * 32, 0
        if start is not None:
            band, index, h, found = start["nextBand"], start["nextFrom"], start["hOut"], start["matchFoundOut"]
        pages = []
        while True:
            values = self.reader.functions.candidates(int(do_request_id), int(round_number), band, index,
                                                      self.page_entries, h, found, beyond).call()
            page = dict(zip(names, values))
            pages.append(page)
            if page["done"]:
                return pages
            band, index, h, found = page["nextBand"], page["nextFrom"], page["hOut"], page["matchFoundOut"]

    def claimers(self, do_request_id: int, count: int) -> List[tuple]:
        """(node, claim word, approvable) of the request's first `count`
        claimers, in the order of their claims."""
        found = []
        while len(found) < count:
            nodes, claims, approvable = self.reader.functions.claimersOf(
                int(do_request_id), len(found), min(CLAIMERS_PAGE, count - len(found))).call()
            if not nodes:
                break
            found.extend(zip(nodes, claims, approvable))
        return found

    def bid_quote_pages(self, do_request_id: int, min_score: int) -> List[Dict[str, Any]]:
        """The bidQuote pages over the nodes at or above `min_score` (D92),
        each page carrying the lowest bid the pages before it found."""
        names = _outputs(reader_abi, "bidQuote")
        band, index, carry = 49, 0, 0
        pages = []
        while True:
            values = self.reader.functions.bidQuote(int(do_request_id), int(min_score), band, index,
                                                    self.page_entries, carry).call()
            page = dict(zip(names, values))
            pages.append(page)
            if page["done"]:
                return pages
            band, index, carry = page["nextBand"], page["nextFrom"], page["minBidWei"]

    def bid_quote_for(self, terms: Dict[str, int], template_name: str, min_score: int) -> Dict[str, int]:
        """bidQuoteFor over its pages for the terms of a request about to be
        added (`epcUnits` the minimum EPC, 0 for none): the nodes counted and
        the lowest bid at which one matches (2^256 - 1: none), at the network
        price of the read."""
        band, index, carry, counted = 49, 0, 0, 0
        while True:
            values = self.reader.functions.bidQuoteFor(
                terms["cpu"], terms["memGB"], terms["storageGB"], terms["bandwidth"], terms["hours"],
                terms["needGflops"], terms["ceilGflops"], terms["epcUnits"], template_key(template_name),
                int(min_score), band, index, self.page_entries, carry).call()
            page = dict(zip(_outputs(reader_abi, "bidQuoteFor"), values))
            counted += int(page["counted"])
            if page["done"]:
                return {"counted": counted, "minBidWei": int(page["minBidWei"]), "baseNowWei": int(page["baseNowWei"])}
            band, index, carry = page["nextBand"], page["nextFrom"], page["minBidWei"]

    def tier_score(self, do_request_id: int) -> int:
        """The top quarter's boundary of the request's round (D138, D152),
        tierScore paged over its two passes."""
        band, index, carry = 49, 0, [0] * 7
        while True:
            score, carry, band, index, done = self.reader.functions.tierScore(
                int(do_request_id), band, index, self.page_entries, carry).call()
            if done:
                return int(score)

    def chain_time(self) -> int:
        """The timestamp of the latest block."""
        return int(self.w3.eth.get_block("latest")["timestamp"])

    def request_status(self, do_request_id: int) -> int:
        """The status the storage holds for the DO request
        (Models.RequestStatus: 0 AVAILABLE, 1 BOOKED, 2 CANCELED)."""
        return int(self.pox.functions._getDORequest(int(do_request_id)).call()[7])

    def order_approved_at(self, order_id: int) -> int:
        return int(self.pox.functions.orderApprovedAt(int(order_id)).call())

    def order_started_at(self, order_id: int) -> int:
        return int(self.pox.functions.orderStartedAt(int(order_id)).call())

    def order_result_at(self, order_id: int) -> int:
        return int(self.pox.functions.orderResultAt(int(order_id)).call()[0])

    def order_marked(self, order_id: int) -> bool:
        """Whether noteAmbiguous has marked the order: PoxMatching's record
        of it is noted (bit 0 of ambiguousOf's word)."""
        return bool(int(self.matching.functions.ambiguousOf(int(order_id)).call()) & 255)

    def image_epc_units(self, image_cid: str) -> int:
        """The EPC need, in units of 64 MiB, the image registry PoxMatching
        names records for the securelock image `image_cid` (imageEpcUnits;
        D200): 0 when PoxMatching names no registry. A read the registry
        does not answer is raised."""
        registry = self.matching.functions.imageRegistry().call()
        if int(registry, 16) == 0:
            return 0
        images = self.w3.eth.contract(address=registry, abi=image_registry_abi)
        return int(images.functions.imageEpcUnits(image_cid).call())

    def image_records(self, image_cid: str) -> Dict[str, Any]:
        """What the image registry PoxMatching names (ECImageRegistryV4)
        and its SessionRegistry hold for the securelock image `image_cid`:
        `registry` (None when PoxMatching names none), `records` (an
        ImageRecords of imageRecords, None without a registry),
        `release_language` (the language of the default release kind 1
        records name, else None), the session it is bound to (`session`,
        zero for none), the newest version of that session's name (`latest`)
        and the image that version is bound to (`current_image`). The
        session sessionOfImage names counts only when it is the securelock's
        own: its record's name is the session the registry's securelock
        table holds for the CID (getImageSession). A CID can stand in both of
        the registry's tables and sessionOfImage names its last binding, so
        a binding to the trustedzone table's session, or a CID outside the
        securelock table (getImageSession refuses it), is no session of the
        image's."""
        registry = self.matching.functions.imageRegistry().call()
        found = {"registry": None, "records": None, "release_language": None, "session": b"\x00" * 32,
                 "latest": b"\x00" * 32, "current_image": None}
        if int(registry, 16) == 0:
            return found
        found["registry"] = registry
        images = self.w3.eth.contract(address=registry, abi=image_registry_abi)
        held = dict(zip(_outputs(image_registry_abi, "imageRecords"), images.functions.imageRecords(image_cid).call()))
        records = ImageRecords(int(held["kind"]), int(held["release"]), bool(held["networkOn"]),
                               int(held["enclaveMemoryGiB"]), bool(held["minScoreSet"]), int(held["minScore"]))
        found["records"] = records
        if records.kind == KIND_DEFAULT_RELEASE:
            found["release_language"] = int(images.functions.defaultRelease(records.release).call()[0])
        sessions_address = images.functions.sessionRegistry().call()
        if int(sessions_address, 16) == 0:
            return found
        sessions = self.w3.eth.contract(address=sessions_address, abi=session_registry_abi)
        session = bytes(sessions.functions.sessionOfImage(image_cid).call())
        if int.from_bytes(session, "big") == 0:
            return found
        name = sessions.functions.record(session).call()[2]
        own = _refused_as(lambda: images.functions.getImageSession(image_cid).call(), None)
        if not own or own != name:
            return found
        found["session"] = session
        latest = bytes(sessions.functions.latest(name).call())
        found["latest"] = latest
        if latest != session and int.from_bytes(latest, "big") != 0:
            found["current_image"] = sessions.functions.record(latest).call()[5]
        return found
