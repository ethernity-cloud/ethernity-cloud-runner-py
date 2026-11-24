"""A request served by claims (MATCHING-DESIGN.md section 8): the checks
before its V2 add, the approval of a claim by the rule of 3.10, the raise of
3.15, the order that does not start (expireUnstarted) or expires
(expireOrder and noteRefund), the report of its end by class and the
noteAmbiguous the members have not sent (3.16, 3.19).

EthernityCloudRunner builds a ClaimsPath for a request on a network whose
PoX's pricing names a PoxMatching when claimsOn() answers true before the
add, on the PoxMatchReader PoxMatching names; on every other network, and
while claims are off, it serves the request without claims (8.4), with V2
terms (TermedRequest) when the task settings give them with an escrow."""
import logging
import time
from collections import namedtuple
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from web3 import Web3

from . import matching
from .contract.operation.matchingContract import MatchingContracts, send_v2_add
from .contract.operation.protocolContract import protocolContract

# How long after an order's result the runner sends noteAmbiguous itself
# when the validators' members have not (section 8 item 16).
NOTE_AMBIGUOUS_AFTER_SECONDS = 3_600
# The number of matching nodes of the approval's round a noteAmbiguous names
# as its hints, the proof that three nodes could serve the request (3.19).
HINT_NODES = 3
GAS_LEVEL_DEFAULT = 10**18

# The task settings a request with V2 terms reads from the resources of run()
# and run_session() (section 8 items 1, 5, 6, 9, 10, 12 and 16), the V2 keys
# among them in V2_KEYS: max_price_per_cu_hour_wei, the bid per CU-hour, is
# required with any of them; escrow_wei is the escrow the add pulls, on the
# claims path the most it may pull (the escrow itself is the reader's
# escrowFor at the request's terms); max_gflops (the GFLOPS ceiling, 0 for
# none), required_gflops (0: one CU, D38), relays_per_hour and gas_level (the
# chain fee's) have defaults (OD26: 0, 0 and 1e18); epc_mib is the client's
# EPC figure in MiB, rounded up to units of 64 MiB (OD23); and
# max_bid_per_cu_hour_wei is the bid ceiling a raise stays within (none: the
# quote is reported and nothing is raised). The claims path also reads
# min_node_score, the minimum score as points (0.50), 0 switching the test
# off, and recent_failure_slots, allow_marked_image, expire_unstarted,
# note_refund and note_ambiguous, the switches of 3.10, 8.12, 8.9, 8.10 and
# 8.16. Each bound the PoX sets on the terms (matching.MAX_PRICE_WEI,
# MIN_GAS_LEVEL, MAX_GAS_LEVEL, max_gflops_arg) is tested before anything is
# sent, and a V2 add takes one instance (validators 1).
ClaimsSettings = namedtuple("ClaimsSettings", "bid_wei escrow_wei max_gflops required_gflops relays_per_hour "
                                              "gas_level max_bid_wei min_score recent_failure_slots "
                                              "allow_marked_image expire_unstarted note_refund note_ambiguous "
                                              "epc_units")
V2_KEYS = ("max_price_per_cu_hour_wei", "escrow_wei", "max_gflops", "required_gflops", "relays_per_hour",
           "gas_level", "max_bid_per_cu_hour_wei", "epc_mib")


def _whole(resources: Dict[str, Any], key: str, default: Optional[int] = None) -> Optional[int]:
    value = resources.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"the task setting {key} must be a whole number of 0 or more, not {value!r}")
    return value


def _within(key: str, value: Optional[int], low: int, high: int) -> Optional[int]:
    if value is not None and not low <= value <= high:
        raise ValueError(f"the task setting {key} must be {low} to {high}, not {value}: the PoX refuses a request "
                         "outside that bound")
    return value


def v2_settings(resources: Dict[str, Any]) -> Optional[ClaimsSettings]:
    """The ClaimsSettings of a run's resources, None when they give none of
    V2_KEYS. Raises ValueError, before anything is sent, for V2 keys
    without a bid, for an escrow_wei of 0, for a setting out of its range or
    out of the PoX's bound, and for more than one instance (validators)."""
    if not any(resources.get(key) is not None for key in V2_KEYS):
        return None
    bid = _whole(resources, "max_price_per_cu_hour_wei")
    escrow = _whole(resources, "escrow_wei")
    if not bid or escrow == 0:
        raise ValueError(
            "A request with V2 terms needs the task setting max_price_per_cu_hour_wei (the bid per CU-hour, "
            "wei), above 0; escrow_wei, when given, is the escrow addDORequestV2 pulls, above 0.")
    validators = resources.get("validators") or 1
    if validators != 1:
        raise ValueError(f"A request with V2 terms takes one instance; the task setting validators is "
                         f"{validators!r}. Give validators 1, or leave the V2 keys out for a legacy request.")
    max_gflops = _whole(resources, "max_gflops", 0)
    required = _whole(resources, "required_gflops", 0)
    epc_units = matching.epc_units_of_mib(_whole(resources, "epc_mib", 0))
    matching.max_gflops_arg(required, max_gflops, epc_units)
    min_score = resources.get("min_node_score")
    return ClaimsSettings(
        _within("max_price_per_cu_hour_wei", bid, 1, matching.MAX_PRICE_WEI), escrow, max_gflops, required,
        _whole(resources, "relays_per_hour", 0),
        _within("gas_level", _whole(resources, "gas_level", GAS_LEVEL_DEFAULT), matching.MIN_GAS_LEVEL,
                matching.MAX_GAS_LEVEL),
        _within("max_bid_per_cu_hour_wei", _whole(resources, "max_bid_per_cu_hour_wei"), 1, matching.MAX_PRICE_WEI),
        None if min_score is None else matching.score_units(min_score),
        _whole(resources, "recent_failure_slots", matching.DEFAULT_RECENT_FAILURE_SLOTS),
        bool(resources.get("allow_marked_image", False)), bool(resources.get("expire_unstarted", True)),
        bool(resources.get("note_refund", True)), bool(resources.get("note_ambiguous", True)), epc_units)


def claims_settings(resources: Dict[str, Any]) -> ClaimsSettings:
    """The ClaimsSettings of a request served by claims (v2_settings).
    Raises ValueError, before anything is sent, for a request without a bid
    and as v2_settings does."""
    settings = v2_settings(resources)
    if settings is None:
        raise ValueError(
            "This network serves DO requests by claims (PoxMatching's claimsOn() is true), so a request is added "
            "with V2 terms: give the task setting max_price_per_cu_hour_wei (the bid per CU-hour, wei), above 0; "
            "escrow_wei, when given, is the most addDORequestV2 may pull, above 0.")
    return settings


class NoParameterSet(Exception):
    """requestInfo names no parameter set in force for the request
    (matching.NO_PARAMETER_SET): it has no schedule, so no claim on it is
    approved by the rule of 3.10."""


class ClaimsOff(Exception):
    """The parameter set the request takes has claims off (requestInfo's
    `claims`): no claim on it is made or approved, and it is served as a
    request without claims (8.4)."""


class NoClaimsNow(Exception):
    """The request takes no claims now (matching.takes_claims): the storage
    no longer holds it AVAILABLE, or it is past maxRequestAgeSeconds. No
    claim on it is approved and its bid is not raised."""


def utc(seconds: int) -> str:
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def pinned_ban(chain: MatchingContracts, node: str) -> Optional[str]:
    """Why no order can be placed on `node` now (D33, 8.11): the message
    naming the end of its ban, or None for a node that is not banned."""
    banned_until = int(chain.node_standing(node)[2])
    now = chain.chain_time()
    if now < banned_until:
        return (f"The node {node} is banned until {utc(banned_until)} ({banned_until}): no order can be placed on "
                "it before then, so the request pinned to it is not sent.")
    return None


# A request's state on the claims path, kept per round stamp: the round's
# schedule, the `candidates` pages it was computed from, whether they reach
# the roll's end (`whole`), and the minimum score and the excluded nodes the
# runner applies in the round.
_Round = namedtuple("_Round", "stamp schedule pages whole min_score excluded")


class ClaimsPath:
    """One request served by claims, from the checks before its add to the
    report of its order's end. `runner` is the EthernityCloudRunner whose
    run this is, `chain` the run's MatchingContracts."""

    def __init__(self, runner: Any, chain: MatchingContracts, settings: ClaimsSettings) -> None:
        self.runner = runner
        self.chain = chain
        self.settings = settings
        self.logger = runner.logger
        self.image_cid: Optional[str] = None
        self.template: Optional[matching.Template] = None
        self.envelope = matching.ENVELOPE_WHOLE_PASS
        self.default_class = False
        # The image's records in the image registry (matching.ImageRecords;
        # None when PoxMatching names no registry) and the dApp's minimum
        # operator score they hold (matching.dapp_minimum).
        self.records: Optional[matching.ImageRecords] = None
        self.dapp_min_score: Optional[int] = None
        # The request's memory need, the larger of the client's memory and
        # the image's enclave memory (matching.memory_need), and its minimum
        # EPC in units of 64 MiB (matching.minimum_epc), set before the add.
        self.memory_gb: Optional[int] = None
        self.epc_units: Optional[int] = None
        # The escrow the add pulls, escrowFor at the request's terms.
        self.escrow_wei: Optional[int] = None
        self.params: Optional[Dict[str, int]] = None
        self.round: Optional[_Round] = None
        self.hints: List[int] = []
        # True once await_approval found the request's set with claims off.
        self.claims_off = False
        self._told = set()

    def notice(self, text: str, level: int = logging.WARNING) -> None:
        """Tells the client (EthernityCloudRunner._matching_notice)."""
        self.runner._matching_notice(text, level)

    def _notice_once(self, key: Any, text: str, level: int = logging.WARNING) -> None:
        if key not in self._told:
            self._told.add(key)
            self.notice(text, level)

    # ------------------------------------------------------- before the add

    def check_before_add(self, image_cid: str, template_name: str) -> None:
        """The reads before the add (8.1, 8.6, 8.12, 8.13, 3.19): the
        template's record and the envelope its mark chooses; the image's
        health, a marked image refused unless the task settings allow it; the
        image registry's records, told to the client (the kind, the network
        flag, the enclave memory and the dApp's minimum operator score, which
        the runner applies: D138), an image its session name's newest version
        is not bound to refused with the dApp's current image named; the
        request's memory need (the image's enclave memory when it is above
        the client's memory) and its minimum EPC (the image's recorded need,
        the client's epc_mib and one unit), each told to the client; the
        class; and the quote at the request's terms. Each refusal is a
        ValueError raised before anything is sent, a registry that does not
        answer the EPC need's read among them."""
        self.image_cid = image_cid
        self.template = self.chain.template(template_name)
        self.envelope = matching.envelope_for(self.template)
        if self.envelope == matching.ENVELOPE_CHUNKED:
            self.notice(f"The template {template_name} is marked: its trustedzone reads the chunked envelope, which "
                        "this runner does not write yet; the payload and the input go in the whole-pass format, "
                        "which that trustedzone reads up to its whole-pass bound.")
        s7, f7, nodes, owners, marked = self.chain.image_health(matching.image_key(image_cid))
        if marked:
            text = (f"The image {image_cid} is marked likely broken: in the last 7 days {f7} of its counted orders "
                    f"failed and {s7} succeeded, on {nodes} different nodes and from {owners} different data owners.")
            if not self.settings.allow_marked_image:
                raise ValueError(text + " The request is not sent; set allow_marked_image to send it, and only "
                                        "operators that opted in answer it.")
            self.notice(text + " allow_marked_image is set: the request is sent.")
        elif s7 == 0 and f7 == 0:
            self.notice(f"The image {image_cid} has had no counted order in the last 7 days, so no mark of its "
                        "health can show.", logging.INFO)
        found = self.chain.image_records(image_cid)
        self.records = found["records"]
        self.dapp_min_score = matching.dapp_minimum(self.records)
        if self.records is not None:
            self.notice(matching.records_text(image_cid, self.records, found["release_language"]), logging.INFO)
        if found["current_image"]:
            raise ValueError(f"The image {image_cid} is not the one its session name's newest version is bound to: "
                             f"the dApp's current image is {found['current_image']}. The request is not sent.")
        client_memory = protocol_terms(self.runner.resources)["memory"]
        self.memory_gb = matching.memory_need(client_memory, self.records)
        if self.memory_gb > client_memory:
            self.notice(f"The image {image_cid} records an enclave memory of {self.memory_gb} GiB, above the "
                        f"request's memory of {client_memory} GB: the request needs {self.memory_gb} GB.",
                        logging.INFO)
        try:
            image_units = self.chain.image_epc_units(image_cid)
        except Exception as e:
            raise ValueError(f"The image registry did not answer the EPC need of the image {image_cid} "
                             f"(imageEpcUnits: {type(e).__name__}: {e}): the request is not sent.") from e
        self.epc_units = matching.minimum_epc(image_units, self.settings.epc_units)
        self.notice(f"The request states a minimum EPC of {self.epc_units} units of {matching.EPC_UNIT_MIB} MiB "
                    f"({self.epc_units * matching.EPC_UNIT_MIB} MiB): the image records {image_units} and the client "
                    f"gives {self.settings.epc_units}.", logging.INFO)
        default_release = self.records is not None and self.records.kind == matching.KIND_DEFAULT_RELEASE
        self.default_class = bool(
            default_release and self.template.marked and not self.runner.is_unsafe()
            and int.from_bytes(found["session"], "big") != 0 and found["latest"] == found["session"])
        if self.template.marked and not self.default_class:
            kind = (f" ({matching.kind_text(self.records, found['release_language'])})"
                    if self.records is not None and self.records.kind != matching.KIND_NONE else "")
            self.notice(f"The image is of the custom class{kind}: a code 20 or 62 of this request is paid to the "
                        "operator, and the developer and the client carry that risk; the minimum operator score is "
                        "their protection.", logging.INFO)
            if self.settings.min_score is not None:
                instead = ("the dApp's minimum operator score of "
                           f"{self.dapp_min_score / matching.SCORE_UNITS_PER_POINT:.4f}"
                           if self.dapp_min_score is not None else "the top tier")
                self.notice(f"The minimum node score is set to {self.settings.min_score / 10_000:.4f} for this "
                            f"request, in place of {instead}: a 20 or 62 of it is paid to the operator at the "
                            "client's risk.")
        self._quote_before_add()

    def _quote_before_add(self) -> None:
        terms = self.request_terms()
        word = self.max_gflops()
        need, ceiling = matching.need_of(word)
        minimum = matching.minimum_score(self.settings.min_score, self.dapp_min_score, self.default_class,
                                         self.default_class and self.chain.minimum_on(), 0)
        quote = self.chain.bid_quote_for(
            {"cpu": terms["cpu"], "memGB": terms["memory"], "storageGB": terms["storage"],
             "bandwidth": terms["bandwidth"], "hours": terms["duration"], "needGflops": need,
             "ceilGflops": ceiling, "epcUnits": matching.epc_of(word)}, self.template_name(), minimum)
        if quote["counted"] == 0 or quote["minBidWei"] == matching.UINT256_MAX:
            self.notice("No listed node covers the request's resources and template: nobody can claim it at any bid.")
            return
        text = (f"The lowest bid at which a listed node matches is {quote['minBidWei']} wei per CU-hour, at the "
                f"network price of {quote['baseNowWei']}; the request bids {self.settings.bid_wei}.")
        self.notice(text, logging.INFO if self.settings.bid_wei >= quote["minBidWei"] else logging.WARNING)

    def template_name(self) -> str:
        return self.runner.trustedZoneImage or self.runner.securelock_enclave

    def request_terms(self) -> Dict[str, int]:
        """The resources the request is added with (protocol_terms), its
        memory the memory need set before the add."""
        terms = protocol_terms(self.runner.resources)
        if self.memory_gb is not None:
            terms["memory"] = self.memory_gb
        return terms

    def max_gflops(self) -> int:
        """The V2 add's maxGflops: the minimum EPC set before the add, the
        required GFLOPS and the ceiling of the settings."""
        s = self.settings
        return matching.max_gflops_arg(s.required_gflops, s.max_gflops, self.epc_units or 0)

    def check_escrow(self, metadata1: str) -> int:
        """The escrow the add pulls, the reader's escrowFor at the request's
        terms and `metadata1` (its fields 1 and 2, the image and the
        template, carry the publishers' fees), told to the client; the
        wallet's balance against it; and the wallet's allowance for the PoX,
        approved for exactly the escrow when below it. Returns the escrow, in
        wei. Raises ValueError, before anything is sent, for an escrow above
        the task setting escrow_wei and for a wallet below it."""
        s = self.settings
        terms = self.request_terms()
        escrow = self.chain.escrow_for(terms["duration"], s.bid_wei, self.max_gflops(), s.relays_per_hour,
                                       s.gas_level, metadata1)
        wei = escrow["escrowWei"]
        if s.escrow_wei is not None and wei > s.escrow_wei:
            raise ValueError(f"The request's escrow at its terms is {wei} wei, above the task setting escrow_wei of "
                             f"{s.escrow_wei}: the request is not sent.")
        self.notice(f"The request's escrow is {wei} wei: the work {escrow['workWei']} at {escrow['escrowGflops']} "
                    f"GFLOPS, the fees on it (the publishers' {escrow['trustedZoneFee']} % and "
                    f"{escrow['secureLockFee']} %) and the chain fee {escrow['chainFeeWei']}.", logging.INFO)
        balance = Web3.to_wei(self.runner._read_before_request(self.runner.contract.get_balance), "ether")
        if balance < wei:
            raise ValueError(f"Insufficient wallet balance: the request's escrow is {wei} wei of "
                             f"{self.runner.network_config.TOKEN_NAME} and the wallet holds {balance}.")
        self._allow(wei)
        self.escrow_wei = wei
        return wei

    def _allow(self, wei: int) -> None:
        runner = self.runner
        wallet = runner.signer.address
        protocol = runner.contract.get_protocol_address()
        allowance = runner._read_before_request(
            lambda: runner.token_contract.functions.allowance(wallet, protocol).call())
        if allowance >= wei:
            return
        receipt = runner.poll_transaction(runner._sender().set_allowance_wei(wei), max_attempts=100)
        if not receipt or receipt["status"] != 1:
            raise ValueError("Allowance approval failed.")

    def add_request(self, metadata: List[str]) -> str:
        """addDORequestV2 with the run's resources, the memory need, the
        minimum EPC and the V2 terms."""
        s = self.settings
        return self.chain.add_do_request_v2(self.request_terms(), s.bid_wei, self.max_gflops(), s.relays_per_hour,
                                            s.gas_level, metadata)

    # ------------------------------------------------------- the approval

    def await_approval(self, do_request: int, wait_seconds: float) -> Optional[int]:
        """Reads the request at every block and approves a claim by the rule
        of 3.10, raising the bid by 3.15 when no claim the runner would
        approve can come; returns the order the approval placed, or None
        when `wait_seconds` pass without one. Only a settled read is acted
        on; a new round or stamp reads the round again. The wait ends with
        None at once when no parameter set is in force for the request, when
        it takes no claims now (NoClaimsNow: no longer AVAILABLE, or past
        maxRequestAgeSeconds), and when its set has claims off, which also
        sets claims_off: the request is then served without claims."""
        deadline = time.monotonic() + wait_seconds
        while self.runner.is_running():
            if time.monotonic() >= deadline:
                return None
            try:
                order = self._tick(do_request)
                if order is not None:
                    return order
            except (NoParameterSet, NoClaimsNow) as e:
                self.notice(str(e))
                return None
            except ClaimsOff as e:
                self.claims_off = True
                self.notice(str(e))
                return None
            except (matching.StampChanged, matching.Unsettled) as e:
                self.logger.debug(f"request {do_request}: {e}; read again")
                self.round = None
            except Exception as e:
                self.logger.warning(f"request {do_request}: a read of the claims failed ({type(e).__name__}: {e}); "
                                    "read again at the next block")
            time.sleep(self.runner.block_time)
        return None

    def _parameters(self, do_request: int, info: Dict[str, Any]) -> Dict[str, int]:
        """The parameter set request `do_request` takes, the one its
        requestInfo `info` names, read once. Raises NoParameterSet when none
        is in force for it."""
        if self.params is None:
            index = int(info["parameterSet"])
            if index == matching.NO_PARAMETER_SET:
                raise NoParameterSet(f"No parameter set of PoxMatching is in force for request {do_request}: it has "
                                     "no schedule, and no claim on it is approved.")
            self.params = self.chain.parameter_set(index)
        return self.params

    def _tick(self, do_request: int) -> Optional[int]:
        info = self.chain.request_info(do_request)
        if not info["settled"]:
            return None
        params = self._parameters(do_request, info)
        if not info["claims"]:
            raise ClaimsOff(f"The parameter set request {do_request} takes has claims off: no claim on it is "
                            "approved, and it is served without claims (a node places its order and the runner "
                            "approves it).")
        now = self.chain.chain_time()
        status = self.chain.request_status(do_request)
        if not matching.takes_claims(info["claims"], status, info["createdAt"], params["maxRequestAgeSeconds"], now):
            age = int(info["createdAt"]) + int(params["maxRequestAgeSeconds"])
            why = (f"it is past maxRequestAgeSeconds since {utc(age)}" if status == matching.REQUEST_AVAILABLE
                   else f"the storage holds it with status {status}, not AVAILABLE")
            raise NoClaimsNow(f"Request {do_request} takes no claims now ({why}): no claim on it is approved and "
                              "its bid is not raised.")
        stamp = bytes(info["roundStamp"])
        if self.round is None or self.round.stamp != stamp:
            self.round = self._read_round(do_request, info)
        rnd = self.round
        claims, can_claim = self._claims_now(do_request, info, rnd)
        nodes = set(rnd.schedule.mandated) | set(claims)
        slot_now = self.chain.chain_time() // self.chain.slot_seconds()
        standings = {n: self._standing(n, n in claims or can_claim.get(n, True)) for n in nodes}
        decision = self._decide(info, rnd, claims, standings, slot_now)
        if decision.rule == 3 and decision.approve not in rnd.schedule.position and not rnd.whole:
            self.round = rnd = self._read_beyond(do_request, info, rnd)
            decision = self._decide(info, rnd, claims, standings, slot_now)
        if decision.approve:
            return self._approve(do_request, decision, claims[decision.approve])
        if decision.wait:
            return None
        if decision.below_minimum:
            self._notice_once(("below", stamp), (
                f"Claims of {', '.join(decision.below_minimum)} stand below the minimum node score of "
                f"{rnd.min_score / 10_000:.4f}: none is approved, and lowering min_node_score would approve one."))
        self._consider_raise(do_request, info, rnd, claims, standings)
        return None

    def _decide(self, info: Dict[str, Any], rnd: _Round, claims: Dict[str, matching.ClaimView],
                standings: Dict[str, matching.Standing], slot_now: int) -> matching.Decision:
        return matching.decide_approval(
            rnd.schedule.mandated, rnd.schedule.position, claims, standings, rnd.excluded, int(info["closedStep"]),
            rnd.min_score, self.settings.recent_failure_slots, slot_now, int(info["roundBlock"]),
            int(self.params["stepBlocks"]), int(self.params["leadBlocks"]))

    def _read_round(self, do_request: int, info: Dict[str, Any]) -> _Round:
        """The round of `info`: its list read from the top of the roll to the
        end of the stop band, its schedule, the minimum score the runner
        applies in it and the nodes it excludes. A read whose matching count
        stayed below maxSteps, or whose stop band is 0, reached the roll's
        end."""
        stamp = bytes(info["roundStamp"])
        max_steps = int(self.params["maxSteps"])
        if info["ranked"]:
            pages = self.chain.candidate_pages(do_request, int(info["round"]))
            read = matching.merge_candidates(pages, max_steps)
            if read.stamp != stamp:
                raise matching.StampChanged("the list read answered another round stamp than requestInfo")
            whole = read.match_found < max_steps or read.stop_band == 0
        else:
            pages = []
            read = matching.ListRead(stamp, [], matching.ZERO_HASH, 0, 0, True)
            whole = True
        self.hints = hint_words(read.entries)
        return _Round(stamp, matching.Schedule(read.entries, bytes(info["seed"]), max_steps), pages, whole,
                      self._minimum(do_request), self._excluded())

    def _read_beyond(self, do_request: int, info: Dict[str, Any], rnd: _Round) -> _Round:
        """The round with the entries below the stop band read on with
        `beyond` from the last page of its read (4.6), for the order of rule
        3."""
        pages = rnd.pages + self.chain.candidate_pages(do_request, int(info["round"]), True, rnd.pages[-1])
        read = matching.merge_candidates(pages, int(self.params["maxSteps"]))
        if read.stamp != rnd.stamp:
            raise matching.StampChanged("the read on with beyond answered another round stamp")
        schedule = matching.Schedule(read.entries, bytes(info["seed"]), int(self.params["maxSteps"]))
        return rnd._replace(schedule=schedule, pages=pages, whole=True)

    def _minimum(self, do_request: int) -> int:
        """The minimum score of the round (3.10 rule 5, D138): the setting,
        else the dApp's minimum operator score its records hold, else for a
        dApp of the default class D62's default once minimumOn() answers
        true, else the top tier of the round."""
        s = self.settings
        if s.min_score is not None:
            return s.min_score
        if self.dapp_min_score is not None:
            return self.dapp_min_score
        if self.default_class:
            return matching.minimum_score(None, None, True, self.chain.minimum_on(), None)
        return matching.minimum_score(None, None, False, False, self.chain.tier_score(do_request))

    def _excluded(self) -> set:
        """The nodes whose claims the runner approves for no request of this
        image: those of its local list, and for a paid class the nodes of
        the image's counted failures of the last 7 days, read from each
        failure's order (3.19)."""
        now = self.chain.chain_time()
        excluded = set(self.runner.local_list.nodes(self.image_cid, now))
        if not self.default_class:
            for failure in matching.recent_health_failures(self.chain.health_words(
                    matching.image_key(self.image_cid)), now):
                order = self.runner.protocol_contract.caller()._getOrder(failure.order_id)
                excluded.add(matching.address_text(order[1]))
        return excluded

    def _claims_now(self, do_request: int, info: Dict[str, Any], rnd: _Round) -> tuple:
        """Every claim on the request at this read, each a ClaimView, and
        whether each mandated node can still claim (canClaimOf). Raises
        StampChanged when canClaimOf answers another round stamp."""
        claims: Dict[str, matching.ClaimView] = {}
        for node, word, approvable in self.chain.claimers(do_request, int(info["claimCount"])):
            claim = matching.decode_claim(word)
            if claim is not None:
                claims[matching.address_text(node)] = matching.ClaimView(claim.block, bool(approvable),
                                                                         claim.dp_request_id)
        can_claim: Dict[str, bool] = {}
        if rnd.schedule.mandated:
            stamp, flags = self.chain.can_claim_of(do_request, rnd.schedule.mandated)
            if stamp != rnd.stamp:
                raise matching.StampChanged("canClaimOf answered another round stamp")
            can_claim = {matching.address_text(n): flag for n, flag in zip(rnd.schedule.mandated, flags)}
        return claims, can_claim

    def _standing(self, node: str, can_answer: bool) -> matching.Standing:
        score = int(self.chain.node_standing(node)[0])
        return matching.Standing(score, bool(can_answer), self.chain.last_failure_slot(node))

    def _approve(self, do_request: int, decision: matching.Decision, claim: matching.ClaimView) -> Optional[int]:
        """The approval of the chosen claim, _placeOrder on its offer, made
        as a call first: an approval the call refuses (the claim stopped
        being approvable since the read) is left for the next read."""
        try:
            tx = self.chain.place_order(do_request, claim.dp_request_id)
        except Exception as e:
            self.logger.info(f"the approval of {decision.approve}'s claim is refused now ({e}); read again")
            return None
        receipt = self.runner.poll_transaction(tx, max_attempts=100)
        if not receipt or receipt["status"] != 1:
            self.logger.warning(f"the approval {tx} of {decision.approve}'s claim did not succeed; read again")
            return None
        order = self.chain.placed_order(receipt)
        how = "in its step" if decision.in_time else ("late" if decision.rule == 1 else "after the mandates")
        self.notice(f"Request {do_request}: the claim of {decision.approve} was approved by rule {decision.rule} "
                    f"({how}); order {order}.", logging.INFO)
        return order

    def _consider_raise(self, do_request: int, info: Dict[str, Any], rnd: _Round,
                        claims: Dict[str, matching.ClaimView], standings: Dict[str, matching.Standing]) -> None:
        """Rule 4 of 3.10 with the quote over the nodes at or above the
        round's minimum (D92): a raise within the bid ceiling, followed at
        the next read by the quote read again (3.15)."""
        quote = matching.merge_quote(self.chain.bid_quote_pages(do_request, rnd.min_score))
        if quote.stamp != rnd.stamp:
            raise matching.StampChanged("the quote answered another round stamp")
        counted = [n for n in claims if n not in rnd.excluded and standings[n].score >= rnd.min_score]
        approvable = [n for n in counted if claims[n].approvable]
        decision = matching.decide_raise(quote, len(counted), len(approvable), bool(info["claimedInRound"]),
                                         int(info["stepNow"]), int(self.params["maxSteps"]), int(info["round"]),
                                         int(self.params["maxRounds"]), self.settings.max_bid_wei)
        if decision.action == matching.WAIT:
            return
        if decision.action == matching.REPORT:
            self._notice_once(("raise", rnd.stamp, decision.reason), f"Request {do_request}: {decision.reason}.")
            return
        self._allow(quote.added_escrow_wei)
        tx = self.chain.increase_bid(do_request, decision.bid_wei)
        receipt = self.runner.poll_transaction(tx, max_attempts=100)
        if not receipt or receipt["status"] != 1:
            raise ValueError(f"the raise {tx} of request {do_request} did not succeed")
        self.notice(f"Request {do_request}: {decision.reason}; the escrow grows by {quote.added_escrow_wei} wei.",
                    logging.INFO)
        self.round = None

    # ------------------------------------------------------- the order

    def start_check(self, order_id: int) -> tuple:
        """(started, fault) of the order's start (section 8 item 9): started
        once the PoX holds orderStartedAt; while it does not,
        startTimeoutSeconds (900) after the approval, the order is ended with
        expireUnstarted, made as a call first, and the fault that resubmits
        the task is returned. With the setting off nothing is sent. The
        parameter set is the one requestInfo names for the run's request,
        read here when no approval read it (a pinned request)."""
        if self.chain.order_started_at(order_id):
            return True, None
        if not self.settings.expire_unstarted:
            return False, None
        approved = self.chain.order_approved_at(order_id)
        if self.params is None:
            do_request = int(self.runner.do_request)
            self._parameters(do_request, self.chain.request_info(do_request))
        timeout = int(self.params["startTimeoutSeconds"])
        if self.chain.chain_time() <= approved + timeout:
            return False, None
        try:
            tx = self.chain.expire_unstarted(order_id)
        except Exception as e:
            self.logger.info(f"expireUnstarted of order {order_id} is refused now ({e})")
            return False, None
        receipt = self.runner.poll_transaction(tx, max_attempts=100)
        if not receipt or receipt["status"] != 1:
            return False, None
        self.notice(f"The trustedzone of order {order_id} did not start within {timeout} s of the approval: the "
                    "order was ended with expireUnstarted and its escrow returned; the request is added again.")
        return False, (f"order {order_id} did not start within {timeout} s of its approval: expireUnstarted ended "
                       "it and returned its escrow")

    def expired(self, order_id: int) -> None:
        """Section 8 item 10: an order whose time is up with no result is
        ended with expireOrder once the PoX admits it, then noteRefund
        charges its node (the setting note_refund); one the PoX does not
        admit yet is kept for EthernityCloudRunner.settle_matching()."""
        if not self._expire(order_id):
            self.runner.matching_pending.append({"kind": "expire", "order": order_id, "chain": self.chain,
                                                 "note_refund": self.settings.note_refund})
            self.notice(f"Order {order_id} has no result in its time; the PoX admits expireOrder one pricing epoch "
                        "after its end: settle_matching() sends it then, with noteRefund.")

    def _expire(self, order_id: int) -> bool:
        return expire_order(self.chain, self.runner, order_id, self.settings.note_refund, self.notice)

    def after_result(self, order_id: int, node: str, code: int, result: str) -> Optional[matching.EndReport]:
        """Section 8 item 16 and 3.19 for an order that closed with a result:
        a code 33 is judged by PoxMatching's early33, a 33 before its time
        being settled as a 62; the runner's local list records an end it
        counts; a code 20, 62, 44, 47, 59 or 63, or a 33 before its time, is
        reported by the class the result states; and an end noteAmbiguous
        takes is kept for settle_matching(), which sends it an hour after the
        result when the members have not."""
        now = self.chain.chain_time()
        early = code == matching.CODE_TIMEOUT and self.chain.early33(order_id)
        self.runner.local_list.record(self.image_cid, node, code, now, early)
        report = matching.end_report(code, matching.result_fields(result), early)
        if report is None:
            return None
        self.notice(report.text)
        if report.ambiguous and self.settings.note_ambiguous:
            self.runner.matching_pending.append({"kind": "note", "order": order_id, "chain": self.chain,
                                                 "after": self.chain.order_result_at(order_id)
                                                 + NOTE_AMBIGUOUS_AFTER_SECONDS, "hints": list(self.hints)})
        return report


class TermedRequest:
    """A request added with V2 terms while it is not served by claims (8.4;
    OD26): on a PoX whose VERSION() takes addDORequestV2 (V2_ADD_ABI), with
    the escrow the task setting escrow_wei states, the wallet's balance
    checked against it and the PoX approved for it, in wei, and the add in
    the PoX's form. On a "2.0" PoX the add states the minimum EPC
    (matching.minimum_epc of the image's recorded need, read from the image
    registry the network's PoxMatching names when the PoX's pricing names
    one, and the client's epc_mib); the "1.2" form carries none. No
    minimum operator score is read or applied (D196). `chain` is the
    network's MatchingContracts, None when the pricing names no
    PoxMatching."""

    def __init__(self, runner: Any, version: str, chain: Optional[MatchingContracts], settings: ClaimsSettings) -> None:
        self.runner = runner
        self.version = version
        self.chain = chain
        self.settings = settings
        self.epc_units = 0

    def check_balance(self) -> None:
        """Raises ValueError, before anything is sent, for a wallet whose
        balance is below the request's escrow."""
        runner = self.runner
        balance = Web3.to_wei(runner._read_before_request(runner.contract.get_balance), "ether")
        if balance < self.settings.escrow_wei:
            raise ValueError(f"Insufficient wallet balance: the request's escrow is {self.settings.escrow_wei} wei "
                             f"of {runner.network_config.TOKEN_NAME} and the wallet holds {balance}.")

    def check_escrow(self, image_cid: str) -> None:
        """The minimum EPC of the request's image on a "2.0" PoX, told to
        the client, and the wallet's allowance for the PoX, approved for
        exactly the escrow when below it. Raises ValueError, before anything
        is sent, when a named image registry does not answer the EPC need's
        read, and when the approval does not succeed."""
        runner = self.runner
        if self.version == "2.0":
            try:
                image_units = self.chain.image_epc_units(image_cid) if self.chain is not None else 0
            except Exception as e:
                raise ValueError(f"The image registry did not answer the EPC need of the image {image_cid} "
                                 f"(imageEpcUnits: {type(e).__name__}: {e}): the request is not sent.") from e
            self.epc_units = matching.minimum_epc(image_units, self.settings.epc_units)
            runner._matching_notice(f"The request states a minimum EPC of {self.epc_units} units of "
                                    f"{matching.EPC_UNIT_MIB} MiB: the image records {image_units} and the client "
                                    f"gives {self.settings.epc_units}.", logging.INFO)
        elif self.settings.epc_units:
            runner._matching_notice(f"The PoX answers VERSION() {self.version}, whose addDORequestV2 states no "
                                    "minimum EPC: the task setting epc_mib is not sent.")
        wallet = runner.signer.address
        protocol = runner.contract.get_protocol_address()
        allowance = runner._read_before_request(
            lambda: runner.token_contract.functions.allowance(wallet, protocol).call())
        if allowance < self.settings.escrow_wei:
            receipt = runner.poll_transaction(runner._sender().set_allowance_wei(self.settings.escrow_wei),
                                              max_attempts=100)
            if not mined(receipt):
                raise ValueError("Allowance approval failed.")

    def add_request(self, metadata: List[str]) -> str:
        """addDORequestV2 in the PoX's form with the run's resources and V2
        terms."""
        s = self.settings
        return send_v2_add(self.runner._sender(), self.version, protocol_terms(self.runner.resources), s.bid_wei,
                           matching.max_gflops_arg(s.required_gflops, s.max_gflops, self.epc_units),
                           s.relays_per_hour, s.gas_level, metadata)


def protocol_terms(resources: Dict[str, Any]) -> Dict[str, int]:
    """The resources a DO request is added with: the values of `resources`,
    the defaults of the legacy add for the ones it leaves out."""
    return protocolContract.request_terms(resources)


def hint_words(entries: List[matching.Eligible]) -> List[int]:
    """The hints of a noteAmbiguous (3.19): the first HINT_NODES matching
    entries of the approval's round in roll order, each band << 80 |
    rollIndex << 48 | listedOrdinal << 24 | listedOrdinal; none when fewer
    match."""
    found = [e for e in entries if e.match][:HINT_NODES]
    if len(found) < HINT_NODES:
        return []
    return [e.band << 80 | e.index << 48 | e.listed_ordinal << 24 | e.listed_ordinal for e in found]


def expire_order(chain: MatchingContracts, runner: Any, order_id: int, note_refund: bool, notice) -> bool:
    """expireOrder of `order_id`, made as a call first, then noteRefund when
    `note_refund`; False when the PoX does not admit the expiry yet."""
    try:
        tx = chain.expire_order(order_id)
    except Exception:
        return False
    receipt = runner.poll_transaction(tx, max_attempts=100)
    if not receipt or receipt["status"] != 1:
        return False
    notice(f"Order {order_id} had no result in its time and was expired: its escrow is returned.")
    if note_refund:
        try:
            refund = chain.note_refund(order_id)
            if mined(runner.poll_transaction(refund, max_attempts=100)):
                notice(f"noteRefund recorded order {order_id}'s expiry against its node.", logging.INFO)
            else:
                notice(f"noteRefund {refund} of order {order_id} did not succeed: its receipt is not that of a "
                       "mined transaction of status 1.", logging.INFO)
        except Exception as e:
            notice(f"noteRefund of order {order_id} is refused: {e}", logging.INFO)
    return True


def mined(receipt: Optional[Dict[str, Any]]) -> bool:
    """Whether `receipt` is that of a transaction that succeeded: a receipt
    read before the wait ended, of status 1. A reverted transaction's
    receipt has status 0."""
    return bool(receipt) and int(receipt["status"]) == 1


def settle_pending(runner: Any) -> None:
    """The work a request left for later (EthernityCloudRunner.matching_pending):
    an expiry the PoX now admits, sent with its noteRefund, and a
    noteAmbiguous due an hour after its result that the validators' members
    have not sent, made as a call first. Work that is not due stays; work
    the contracts refuse is dropped."""
    keep = []
    for item in runner.matching_pending:
        chain = item["chain"]
        try:
            if item["kind"] == "expire":
                if not expire_order(chain, runner, item["order"], item["note_refund"], runner._matching_notice):
                    keep.append(item)
                continue
            if chain.chain_time() < item["after"]:
                keep.append(item)
                continue
            if chain.order_marked(item["order"]):
                continue
            tx = chain.note_ambiguous(item["order"], item["hints"])
            if mined(runner.poll_transaction(tx, max_attempts=100)):
                runner._matching_notice(f"noteAmbiguous of order {item['order']} sent: the members had not sent it "
                                        "within an hour of the result.", logging.INFO)
            else:
                runner._matching_notice(f"noteAmbiguous {tx} of order {item['order']} did not succeed: its receipt "
                                        "is not that of a mined transaction of status 1.", logging.INFO)
        except Exception as e:
            runner.logger.info(f"pending {item['kind']} of order {item['order']}: {e}")
    runner.matching_pending = keep
