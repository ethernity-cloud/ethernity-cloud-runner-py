from typing import Any, Dict, List, Optional

from web3 import Web3

from ..abi.matchingAbi import (image_registry as image_registry_abi, matching as matching_abi, pox as pox_abi,
                               reader as reader_abi, session_registry as session_registry_abi)
from ...matching import Template, decode_template, template_key

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
    protocol contract's address, PoxMatching at the network entry's
    MATCHING_ADDRESS and PoxMatchReader at its MATCH_READER_ADDRESS, all on
    the protocol contract's provider. Every transaction is first made as a
    call from the runner's wallet, and sent through the protocol contract's
    _build_sign_send only when the call passes; a call that reverts raises
    what the provider raised and nothing is sent."""

    def __init__(self, contract: Any, matching_address: str, reader_address: str,
                 page_entries: Optional[int] = None) -> None:
        self.contract = contract
        w3 = contract.provider
        self.w3 = w3
        self.pox = w3.eth.contract(address=Web3.to_checksum_address(contract.protocol_address), abi=pox_abi)
        self.matching = w3.eth.contract(address=Web3.to_checksum_address(matching_address), abi=matching_abi)
        self.reader = w3.eth.contract(address=Web3.to_checksum_address(reader_address), abi=reader_abi)
        self.page_entries = int(page_entries or DEFAULT_PAGE_ENTRIES)

    # ------------------------------------------------------------- sends

    def _send(self, contract_fn: Any, name: str) -> str:
        contract_fn.call({"from": self.contract.signer.address})
        return self.contract._build_sign_send(contract_fn, GAS_FLOOR[name])

    def add_do_request_v2(self, resources: Dict[str, int], bid_wei: int, max_gflops: int, relays_per_hour: int,
                          gas_level: int, metadata: List[str]) -> str:
        """addDORequestV2 with the resources of `resources`, one instance, the
        bid per CU-hour, the maxGflops argument (the required GFLOPS and the
        ceiling), the chain fee's relays per hour and gas level, and the four
        metadata strings."""
        fn = self.pox.functions.addDORequestV2(
            resources["cpu"], resources["memory"], resources["storage"], resources["bandwidth"],
            resources["duration"], 1, int(bid_wei), int(max_gflops), int(relays_per_hour), int(gas_level),
            *metadata)
        return self._send(fn, "addDORequestV2")

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

    def request_parameters(self, do_request_id: int) -> Dict[str, int]:
        """The parameter set of a request: the one its record names (the
        index in bits 216 to 223 of requestOf's record), by field name."""
        record, _price = self.matching.functions.requestOf(int(do_request_id)).call()
        index = (int(record) >> 216) & 255
        values = self.matching.functions.parameterSet(index).call()
        return dict(zip(_outputs(matching_abi, "parameterSet"), values))

    def request_info(self, do_request_id: int) -> Dict[str, Any]:
        values = self.reader.functions.requestInfo(int(do_request_id)).call()
        return dict(zip(_outputs(reader_abi, "requestInfo"), values))

    def schedule_of(self, do_request_id: int) -> Dict[str, Any]:
        values = self.reader.functions.scheduleOf(int(do_request_id)).call()
        return dict(zip(_outputs(reader_abi, "scheduleOf"), values))

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
        added: the nodes counted and the lowest bid at which one matches
        (2^256 - 1: none), at the network price of the read."""
        band, index, carry, counted = 49, 0, 0, 0
        while True:
            values = self.reader.functions.bidQuoteFor(
                terms["cpu"], terms["memGB"], terms["storageGB"], terms["bandwidth"], terms["hours"],
                terms["needGflops"], terms["ceilGflops"], template_key(template_name), int(min_score), band, index,
                self.page_entries, carry).call()
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

    def image_records(self, image_cid: str) -> Dict[str, Any]:
        """What the image registry PoxMatching names (ECImageRegistryV4)
        and its SessionRegistry hold for the securelock image `image_cid`:
        `registry` (None when PoxMatching names none), `default_release`
        (hasDefaultRelease), the session it is bound to (`session`, zero for
        none), the newest version of that session's name (`latest`) and the
        image that version is bound to (`current_image`)."""
        registry = self.matching.functions.imageRegistry().call()
        found = {"registry": None, "default_release": False, "session": b"\x00" * 32, "latest": b"\x00" * 32,
                 "current_image": None}
        if int(registry, 16) == 0:
            return found
        found["registry"] = registry
        images = self.w3.eth.contract(address=registry, abi=image_registry_abi)
        found["default_release"] = bool(images.functions.hasDefaultRelease(image_cid).call())
        sessions_address = images.functions.sessionRegistry().call()
        if int(sessions_address, 16) == 0:
            return found
        sessions = self.w3.eth.contract(address=sessions_address, abi=session_registry_abi)
        session = bytes(sessions.functions.sessionOfImage(image_cid).call())
        found["session"] = session
        if int.from_bytes(session, "big") == 0:
            return found
        name = sessions.functions.record(session).call()[2]
        latest = bytes(sessions.functions.latest(name).call())
        found["latest"] = latest
        if latest != session and int.from_bytes(latest, "big") != 0:
            found["current_image"] = sessions.functions.record(latest).call()[5]
        return found
