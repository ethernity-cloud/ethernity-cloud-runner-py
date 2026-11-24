"""The runner's side of PoX 2.0 matching (MATCHING-DESIGN.md 3.10, 3.15,
3.16, 3.19, 4.4 to 4.7 and section 8; pox-smart-contract-litvm
spec/matching.md sections 3 to 9, 13 and 17).

Every value is an integer and every hash keccak256 over the packed bytes of
spec/matching.md section 3. The functions here hold no chain access:
contract/operation/matchingContract.py reads the chain and claims.py drives a
request through them.

- The list of a round from the reader's `candidates` pages (4.5, 4.6): the
  pages merged under one round stamp, the list hash and the matching count
  recomputed from the entries the pages returned, the list's order and the
  mandated sequence (Schedule).
- The runner's approval rule on closed steps (3.10; spec/matching.md 13).
- The raise within the client's bid ceiling (3.10 rule 4, 3.15, D92).
- The minimum score (D62, D71, D88, D138), the recent-failure test (D61) and
  the runner's local list (3.19, D120).
- The three result fields after v5 and the report of an end by class (3.19;
  spec/matching.md 17; section 8 items 15 and 16).
- The stored result's grammar (spec/matching.md 17, "The stored result").
- The template's record and the envelope its mark chooses (3.19; 8.13).
- An image's records in ECImageRegistryV4 (8.12; D126, D138, D150) and the
  request's memory and EPC minimum they set (D150, D200).
- The bounds of a V2 request's terms (spec/matching.md section 4)."""
import re
from collections import namedtuple
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional

from eth_keys import keys
from eth_utils import keccak

SCORE_MAX = 50_000
# The GFLOPS a request that states none requires (D38): one CU.
DEFAULT_NEED_GFLOPS = 100
UINT16_MAX = 2**16 - 1
UINT32_MAX = 2**32 - 1
UINT64_MAX = 2**64 - 1
UINT256_MAX = 2**256 - 1
# One score unit is 0.0001: a score of 1.00 is 10,000 units.
SCORE_UNITS_PER_POINT = 10_000
# The runner's default minimum score, 0.50 (D62), applied once minimumOn()
# answers true (D71, D88).
DEFAULT_MIN_SCORE = 5_000
# The slots one cut costs (D61; 3.10 rule 6): a claimer whose last failed
# order is fewer slots ago is not approved by rules 1 and 2.
DEFAULT_RECENT_FAILURE_SLOTS = 14
# The runner's local list (3.19, D120): no claim of a node is approved for a
# dApp for LOCAL_LIST_SECONDS after LOCAL_LIST_ENDS of the runner's orders of
# that dApp on that node ended, within LOCAL_LIST_SECONDS, in one of
# LOCAL_LIST_CODES or in a code 33 before its time.
LOCAL_LIST_SECONDS = 7 * 86_400
LOCAL_LIST_ENDS = 2
LOCAL_LIST_CODES = frozenset({20, 59, 62, 63})
# Code 33, EXECUTION_TIMEOUT: before its time (PoxMatching's early33) it is
# settled as a 62 (3.19).
CODE_TIMEOUT = 33
# The parameter set requestInfo names for a request none is in force for.
NO_PARAMETER_SET = 256
# The window of an image's health (3.19): the days d - 6 to d.
HEALTH_WINDOW_DAYS = 7
DAY_SECONDS = 86_400
# The result's class, field 17 (spec/matching.md 17).
CUSTOM_CLASS = 0
DEFAULT_CLASS = 1
# The three result fields after the fifteen of v5 (spec/matching.md 17).
RESULT_FIELDS_MIN = 18
RESULT_FIELD_BOUNDS = ((15, UINT64_MAX), (16, UINT64_MAX), (17, 1))
DIGITS = frozenset("0123456789")
# The bounds the PoX 2.0 sets on a V2 request's terms (spec/matching.md
# section 4; Ethernity20Extension.sol _addTermedDORequest and
# _insertDORequest, Ethernity20Extension2.sol increaseBid, PoxPricing's
# chainFeeWei): a bid of 1 to MAX_PRICE_WEI wei per CU-hour at the add and at
# a raise ("price invalid"); a gasLevel of MIN_GAS_LEVEL ("gasLevel below
# average") to MAX_GAS_LEVEL ("gasLevel invalid"); the required GFLOPS at
# most a stated ceiling ("maxGflops invalid"); one instance ("instance
# invalid"); each of the four metadata strings at most MAX_METADATA_BYTES
# bytes ("metadata1 too long", "metadata too long").
MAX_PRICE_WEI = 2**128 - 1
MIN_GAS_LEVEL = 10**18
MAX_GAS_LEVEL = 2**128 - 1
MAX_METADATA_BYTES = 2048
# An EPC figure's unit (spec/matching.md section 16, item 33): 64 MiB; a
# figure is 0 to UINT16_MAX units.
EPC_UNIT_MIB = 64
# The status the storage holds for a DO request (Models.RequestStatus).
REQUEST_AVAILABLE = 0
# The text of a score in points: decimal digits with an optional sign, point
# and exponent, as score_units and runner-js's scoreUnits read it.
DECIMAL_TEXT = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")

ZERO_HASH = b"\x00" * 32


# ------------------------------------------------------------- encodings

def address_bytes(address) -> bytes:
    """The 20 bytes of a hex address in any spelling."""
    text = str(address)
    return bytes.fromhex(text[2:] if text[:2] in ("0x", "0X") else text)


def address_text(address) -> str:
    """A hex address in lower case."""
    return "0x" + address_bytes(address).hex()


def uint(value: int, width: int) -> bytes:
    """The `width`-byte big-endian bytes of `value`."""
    return int(value).to_bytes(width, "big")


def key_of(seed: bytes, node) -> int:
    """A node's key in a request's order: uint256(keccak256(bytes32 seed,
    address node)) (4.4)."""
    return int.from_bytes(keccak(bytes(seed) + address_bytes(node)), "big")


def list_link(h: bytes, node, fit: bool, match: bool) -> bytes:
    """One link of the list hash: keccak256(bytes32 h, address node, uint8
    flags), flags = fit + 2 x match (4.5)."""
    return keccak(bytes(h) + address_bytes(node) + uint(int(bool(fit)) + 2 * int(bool(match)), 1))


def template_key(name: str) -> bytes:
    """The key PoxMatching holds a template under: keccak256 of its name,
    field 2 of metadata1 (4.2)."""
    return keccak(name.encode("utf-8"))


def image_key(image_cid: str) -> bytes:
    """The key PoxMatching holds an image's health under: the first 31 bytes
    of keccak256 of the securelock image, field 1 of metadata1 (spec/matching.md
    section 3)."""
    return keccak(image_cid.encode("utf-8"))[:31]


def max_gflops_arg(required_gflops: int, ceiling_gflops: int, epc_units: int = 0) -> int:
    """The V2 add's maxGflops argument (spec/matching.md section 3): the
    minimum EPC in units of 64 MiB in bits 32 to 47, the required GFLOPS in
    bits 16 to 31 and the ceiling in bits 0 to 15; 0 states none of each.
    One CU is 100 GFLOPS. Raises ValueError for a value outside 0 to 65,535
    and for a required GFLOPS above a stated ceiling, which the PoX refuses
    ("maxGflops invalid")."""
    for name, value in (("required GFLOPS", required_gflops), ("GFLOPS ceiling", ceiling_gflops),
                        ("minimum EPC in units of 64 MiB", epc_units)):
        if not 0 <= int(value) <= UINT16_MAX:
            raise ValueError(f"the {name} of a request must be 0 to {UINT16_MAX}, not {value}")
    if int(ceiling_gflops) != 0 and int(required_gflops) > int(ceiling_gflops):
        raise ValueError(f"the required GFLOPS of a request, {required_gflops}, is above its GFLOPS ceiling of "
                         f"{ceiling_gflops}: the PoX refuses such a request (maxGflops invalid).")
    return (int(epc_units) << 32) | (int(required_gflops) << 16) | int(ceiling_gflops)


def need_of(max_gflops: int) -> tuple:
    """(need, ceiling) of a maxGflops argument (4.2, D38): a request that
    states no required GFLOPS requires its ceiling when that is below 100,
    else 100."""
    ceiling = int(max_gflops) & UINT16_MAX
    need = (int(max_gflops) >> 16) & UINT16_MAX
    if need == 0:
        need = ceiling if 0 < ceiling < DEFAULT_NEED_GFLOPS else DEFAULT_NEED_GFLOPS
    return need, ceiling


def epc_of(max_gflops: int) -> int:
    """The minimum EPC, in units of 64 MiB, of a maxGflops argument: its bits
    32 to 47."""
    return (int(max_gflops) >> 32) & UINT16_MAX


def epc_units_of_mib(mib: int) -> int:
    """An EPC figure in MiB in units of 64 MiB, rounded up (D191, D200; OD23):
    0 for 0. Raises ValueError for a figure above 65,535 units."""
    units = -(-int(mib) // EPC_UNIT_MIB)
    if units > UINT16_MAX:
        raise ValueError(f"an EPC figure is at most {UINT16_MAX * EPC_UNIT_MIB} MiB ({UINT16_MAX} units of "
                         f"{EPC_UNIT_MIB} MiB), not {mib}")
    return units


def minimum_epc(image_units: int, client_units: int) -> int:
    """The minimum EPC a runner states on a request it adds (spec/matching.md
    section 16, item 41; D200): the largest of one unit, the image's recorded
    need (imageEpcUnits) and the client's figure, in units of 64 MiB."""
    return max(1, int(image_units), int(client_units))


def memory_need(client_gb: int, records: Optional["ImageRecords"]) -> int:
    """The memory a request needs (8.12; D150): the larger of the client's
    memory and the enclave memory the image's records hold, in GB; the
    client's alone without records."""
    if records is None:
        return int(client_gb)
    return max(int(client_gb), int(records.enclave_memory_gib))


def check_metadata(metadata: List[str]) -> None:
    """Raises ValueError when one of a V2 add's four metadata strings is
    longer than MAX_METADATA_BYTES bytes of UTF-8, which the PoX refuses."""
    for i, text in enumerate(metadata, start=1):
        size = len(str(text).encode("utf-8", "surrogatepass"))
        if size > MAX_METADATA_BYTES:
            raise ValueError(f"metadata{i} of the request is {size} bytes, above the {MAX_METADATA_BYTES} bytes the "
                             "PoX takes: the request is not sent.")


def score_units(score) -> int:
    """A score given as points (0.50, 1, 4.9) in units of 0.0001, the unit
    nodeStanding answers in; 0 to 5.00. The points are read as the decimal
    text of the value (str(), the shortest text that reads back as a float)
    and rounded half up to a whole unit, as runner-js reads them."""
    text = str(score).strip()
    if isinstance(score, bool) or not DECIMAL_TEXT.fullmatch(text):
        raise ValueError(f"a minimum node score is 0 to 5.00, not {score!r}")
    try:
        units = (Decimal(text) * SCORE_UNITS_PER_POINT).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"a minimum node score is 0 to 5.00, not {score!r}") from None
    if not 0 <= units <= SCORE_MAX:
        raise ValueError(f"a minimum node score is 0 to 5.00, not {score!r}")
    return int(units)


# ------------------------------------------------------------- the clock

def step_at(block: int, round_block: int, step_blocks: int, lead_blocks: int) -> int:
    """step(C) of 4.5 on the clock of a round opened in `round_block`,
    without a bound."""
    lead = round_block + lead_blocks
    if block <= lead:
        return 0
    return 1 + (block - lead - 1) // step_blocks


# ------------------------------------------------------------- the words

# An eligible entry of a list read: the fields of the reader's list word
# (spec/matching.md section 3), the period's tip, the band of the roll array
# the entry stands in and its index there.
Eligible = namedtuple("Eligible", "node score fit match listed_ordinal dp_request_id tip band index")


def place_of(band: int, index: int) -> int:
    """A `candidates` place: band << 32 | the entry's index in its band
    (spec/matching.md section 8)."""
    return int(band) << 32 | int(index)


def decode_eligible(word: int, tip: int, place: int) -> Eligible:
    """An Eligible from a `candidates` word, its tip and its place: the word
    is node << 96 | score << 80 | fit << 73 | match << 72 | listedOrdinal <<
    48 | dpRequestId, the place band << 32 | index, the band being the roll
    array the entry stands in."""
    word = int(word)
    place = int(place)
    return Eligible("0x" + uint(word >> 96, 20).hex(), (word >> 80) & UINT16_MAX, bool((word >> 73) & 1),
                    bool((word >> 72) & 1), (word >> 48) & (2**24 - 1), word & (2**48 - 1), int(tip),
                    (place >> 32) & 255, place & UINT32_MAX)


# A claim record (PoxMatchingState.Claim): the offer, the block and time it
# was mined at, the round it was mined in, its step on that round's clock
# bounded by maxSteps + 1, its state, the steps it states (four bits a round)
# and the tip it was admitted at.
Claim = namedtuple("Claim", "dp_request_id block time round step state stated tip")


def decode_claim(word: int) -> Optional[Claim]:
    """A Claim from a claim word, None for a node with no claim (block 0)."""
    word = int(word)
    block = (word >> 48) & (2**48 - 1)
    if block == 0:
        return None
    packed = (word >> 128) & UINT32_MAX
    return Claim(word & (2**48 - 1), block, (word >> 96) & UINT32_MAX, packed & 15, (packed >> 4) & 15,
                 (packed >> 8) & 15, packed >> 12, word >> 160)


# A trustedzone template's record (PoxMatchingState.Template): its bit, when
# it was registered, its mark, and the release's timeout constants.
Template = namedtuple("Template", "bit registered_at marked registered stop_margin_seconds agent_window_seconds "
                                  "end_budget_seconds chain_lag_seconds start_timeout_seconds")


def decode_template(word: int) -> Template:
    """A Template from the word templateOf answers."""
    word = int(word)
    return Template(word & 255, (word >> 8) & UINT32_MAX, bool((word >> 40) & 255), bool((word >> 48) & 255),
                    (word >> 56) & UINT16_MAX, (word >> 72) & UINT16_MAX, (word >> 88) & UINT16_MAX,
                    (word >> 104) & UINT16_MAX, (word >> 120) & UINT16_MAX)


# The envelope a request's payload and input travel in (8.13): the chunked
# envelope for a marked template's trustedzone (D76), the whole-pass format
# for every other.
ENVELOPE_CHUNKED = "chunked"
ENVELOPE_WHOLE_PASS = "whole-pass"


def envelope_for(template: Optional[Template]) -> str:
    """The envelope the trustedzone of `template` reads: chunked for a
    registered marked template, whole-pass otherwise."""
    return ENVELOPE_CHUNKED if template is not None and template.registered and template.marked else ENVELOPE_WHOLE_PASS


# One of the last 16 counted failures of an image's health
# (PoxMatchingState.HealthFailure): the order, the tags of its node and of
# its request's owner, and the day.
HealthFailure = namedtuple("HealthFailure", "order_id node_tag owner_tag day")
HEALTH_FAILURE_WORDS = slice(3, 19)


def recent_health_failures(words: List[int], now: int) -> List[HealthFailure]:
    """The counted failures healthOf's twenty words hold whose day is in the
    window of 7 days at `now` (days d - 6 to d), the empty entries left
    out."""
    today = int(now) // DAY_SECONDS
    found = []
    for word in list(words)[HEALTH_FAILURE_WORDS]:
        word = int(word)
        failure = HealthFailure(word & (2**48 - 1), (word >> 48) & (2**48 - 1), (word >> 96) & (2**48 - 1),
                                (word >> 144) & UINT32_MAX)
        if failure.day == 0 and failure.order_id == 0:
            continue
        if today - (HEALTH_WINDOW_DAYS - 1) <= failure.day <= today:
            found.append(failure)
    return found


# ------------------------------------------------------------- the list

class StampChanged(Exception):
    """The pages of one list read answered different round stamps: a raise
    or a replaced block came between them, and the read starts again."""


class Unsettled(Exception):
    """A page of a list read was answered at a block that is not settled for
    the round (4.1): nothing is ranked, approved or raised on it."""


ListRead = namedtuple("ListRead", "stamp entries list_hash match_found stop_band done")


def merge_candidates(pages: Iterable[dict], max_steps: int) -> ListRead:
    """One list read from its `candidates` pages in the order they were
    read, each a mapping of the view's answers (roundStamp, eligible, tips,
    places, hOut, matchFoundOut, done, settled). Raises StampChanged when
    two pages answer different stamps, Unsettled for a page not settled,
    and ValueError when the list hash or the matching count computed from
    the entries differs from the one the last page carried (a page left
    out or answered for another read). The entries are those of every page,
    in roll order, each in the band its place names."""
    stamp = None
    entries: List[Eligible] = []
    last = None
    for page in pages:
        if stamp is not None and bytes(page["roundStamp"]) != stamp:
            raise StampChanged("the pages of the list read answered two round stamps")
        stamp = bytes(page["roundStamp"])
        if not page["settled"]:
            raise Unsettled("a page of the list read is not settled for the round")
        for word, tip, place in zip(page["eligible"], page["tips"], page["places"]):
            entries.append(decode_eligible(word, tip, place))
        last = page
    if last is None:
        raise ValueError("a list read needs one page at least")
    h, found, stop = list_hash_of(entries, max_steps)
    if h != bytes(last["hOut"]) or found != int(last["matchFoundOut"]):
        raise ValueError("the list hash or the matching count of the pages is not the one the reader carried")
    return ListRead(stamp, entries, h, found, stop, bool(last["done"]))


def list_hash_of(entries: List[Eligible], max_steps: int) -> tuple:
    """(listHash, matchFound, stopBand) of eligible entries in roll order
    (4.5): every entry of the bands 49 down to stopBand is linked, stopBand
    being the band of the maxSteps-th matching entry, 0 when fewer match."""
    h = ZERO_HASH
    found = 0
    stop = None
    for e in entries:
        if stop is not None and e.band < stop:
            break
        h = list_link(h, e.node, e.fit, e.match)
        if e.match and found < max_steps:
            found += 1
            if found == max_steps:
                stop = e.band
    return h, found, (stop if stop is not None else 0)


class Schedule:
    """The schedule of a round (4.4, 4.5) from its eligible entries in roll
    order: the list's order (band descending, then key, then address), each
    listed node's 1-based position, and the mandated sequence, the first
    maxSteps of F(49), R(49), F(48), R(48), ..., F(0), R(0), with M its
    length. The entries must reach the end of the stop band for the
    mandated sequence; the positions of nodes below it need the entries read
    on with `beyond`."""

    def __init__(self, entries: List[Eligible], seed: bytes, max_steps: int) -> None:
        keys = {e.node: key_of(seed, e.node) for e in entries}
        self.order = sorted(entries, key=lambda e: (-e.band, keys[e.node], int(e.node, 16)))
        self.position = {e.node: i + 1 for i, e in enumerate(self.order)}
        bands: Dict[int, List[Eligible]] = {}
        for e in self.order:
            bands.setdefault(e.band, []).append(e)
        mandated: List[str] = []
        for band in sorted(bands, reverse=True):
            fit = [e.node for e in bands[band] if e.match and e.fit]
            rest = [e.node for e in bands[band] if e.match and not e.fit]
            mandated.extend((fit + rest)[:int(max_steps) - len(mandated)])
        self.mandated = mandated


# ------------------------------------------------------------- approval

# What the runner knows of a node when it decides: its score as nodeStanding
# answers it, whether it can still answer (its period open and its offer
# AVAILABLE and unexpired: 3.10 rule 2), and the slot of its last failed
# order as recordOf answers it (0: none).
Standing = namedtuple("Standing", "score can_answer last_failure_slot")
# A claim as the runner decides on it: the block it was mined at, whether it
# can be approved now (3.11) and the offer an approval places on.
ClaimView = namedtuple("ClaimView", "block approvable dp_request_id")
# The decision of one read: `approve` names the node whose claim is taken,
# by `rule` (1 or 3) and, for rule 1, whether its claim was mined in its
# node's step or earlier; `wait` is true while a mandated step is open;
# with neither, no standing claim exists and `below_minimum` names the
# claimers whose approvable claims the minimum score kept from standing.
Decision = namedtuple("Decision", "approve rule in_time wait below_minimum")


def recent_failure(standing: Standing, slot_now: int, recent_failure_slots: int) -> bool:
    """Whether a node's last failed order is in the last
    `recent_failure_slots` slots (3.10 rule 6): slotNow - lastFailureSlot <
    recentFailureSlots, for a recorded failure."""
    last = int(standing.last_failure_slot)
    return last != 0 and int(slot_now) - last < int(recent_failure_slots)


def decide_approval(mandated: List[str], position: Dict[str, int], claims: Dict[str, ClaimView],
                    standings: Dict[str, Standing], excluded: Iterable[str], closed: int, min_score: int,
                    recent_failure_slots: int, slot_now: int, round_block: int, step_blocks: int,
                    lead_blocks: int) -> Decision:
    """The runner's approval rule at one read (3.10; spec/matching.md 13).
    `mandated` is the round's mandated sequence in step order, `position` the
    list position of each listed node, `claims` every claim on the request,
    `standings` every claimer's and mandated node's standing, `excluded` the
    nodes the runner approves no claim of (its local list, and for a paid
    class the claimers the image's recent counted failures name), `closed`
    the last closed step of the read, all on the clock of the round opened in
    `round_block`.

    A claim stands when it is approvable, its node is not excluded and its
    node's score is at least `min_score`. Rule 1: among the mandated nodes
    whose claim stands, whose last failed order is not recent and whose
    earlier steps are all closed or passed over, the claim mined in its
    node's step or earlier with the lowest step, else the lowest step. A
    mandated node is passed over at once when it cannot answer, its claim is
    not approvable, its failed order is recent or it is excluded; a claim
    below the minimum is treated as absent, so its node's step must close.
    While a mandated step is neither closed nor passed over the runner
    waits. Rule 3: the standing claims, those without a recent failed order
    first, mandated nodes by step, then the list's nodes by position, then
    nodes outside the list by the block of their claim; one with a recent
    failed order only when no other stands."""
    excluded = {address_text(n) for n in excluded}
    claims = {address_text(n): c for n, c in claims.items()}
    standings = {address_text(n): s for n, s in standings.items()}
    mandated = [address_text(n) for n in mandated]

    def recent(n):
        return recent_failure(standings[n], slot_now, recent_failure_slots)

    def stands(n):
        c = claims.get(n)
        return c is not None and c.approvable and n not in excluded and standings[n].score >= min_score

    def passed_over(n):
        c = claims.get(n)
        return (not standings[n].can_answer or (c is not None and not c.approvable) or recent(n)
                or n in excluded)

    done = [j <= closed or passed_over(n) for j, n in enumerate(mandated, start=1)]
    first = None
    for j, n in enumerate(mandated, start=1):
        if not all(done[:j - 1]) or not stands(n) or recent(n):
            continue
        in_time = step_at(claims[n].block, round_block, step_blocks, lead_blocks) <= j
        if in_time:
            return Decision(n, 1, True, False, [])
        if first is None:
            first = n
    if first is not None:
        return Decision(first, 1, False, False, [])
    if not all(done):
        return Decision(None, None, None, True, [])
    standing = [n for n in claims if stands(n)]
    if standing:
        def rank(n):
            if n in mandated:
                return (0, mandated.index(n), 0, 0)
            if n in position:
                return (1, position[n], 0, 0)
            return (2, 0, claims[n].block, int(n, 16))
        fresh = sorted((n for n in standing if not recent(n)), key=rank)
        chosen = fresh[0] if fresh else sorted(standing, key=rank)[0]
        return Decision(chosen, 3, None, False, [])
    below = sorted(n for n, c in claims.items()
                   if c.approvable and n not in excluded and standings[n].score < min_score)
    return Decision(None, None, None, False, below)


# ------------------------------------------------------------- the raise

# The quote for a raise merged over its pages (4.6): the nodes counted, how
# many of them can claim at the round in force, the lowest bid at which one
# of them matches (UINT256_MAX: none counted), the network price of the
# read, the bid in force, and what increaseBid with the bid to send pulls.
Quote = namedtuple("Quote", "stamp counted can_claim_now min_bid_wei base_now_wei bid_wei added_escrow_wei")


def merge_quote(pages: Iterable[dict]) -> Quote:
    """A Quote from the bidQuote pages in the order read, each a mapping of
    the view's answers. The counts add up; the lowest bid is the last
    page's, each page carrying the one before it; the added escrow is the
    last page's (answered with `done`). Raises StampChanged for two stamps."""
    stamp = None
    counted = can_claim = 0
    last = None
    for page in pages:
        if stamp is not None and bytes(page["roundStamp"]) != stamp:
            raise StampChanged("the pages of the quote answered two round stamps")
        stamp = bytes(page["roundStamp"])
        counted += int(page["counted"])
        can_claim += int(page["canClaimNow"])
        last = page
    if last is None:
        raise ValueError("a quote needs one page at least")
    return Quote(stamp, counted, can_claim, int(last["minBidWei"]), int(last["baseNowWei"]), int(last["bidWei"]),
                 int(last["addedEscrowWei"]))


def send_bid(min_bid_wei: int, bid_wei: int) -> int:
    """The bid a raise sends (4.6): max(minBidWei, bid + 1); a quote at or
    below the bid in force names a network price that fell since the round,
    which a raise of one wei stamps."""
    return max(int(min_bid_wei), int(bid_wei) + 1)


# The decision on a raise: `action` is "raise" with the bid to send, "wait"
# while a claim the runner would approve can still come or the contract does
# not admit the raise yet, or "report" when a raise cannot be sent, with
# `reason` saying why.
RaiseDecision = namedtuple("RaiseDecision", "action bid_wei reason")
RAISE = "raise"
WAIT = "wait"
REPORT = "report"


def takes_claims(claims: bool, status: int, created_at: int, max_request_age_seconds: int, now: int) -> bool:
    """Whether a request served by claims takes claims now (spec/matching.md
    section 9, takesClaims; section 16, item 23): its parameter set has
    claims on (requestInfo's `claims`), the storage holds it AVAILABLE, and
    it is at most maxRequestAgeSeconds old at `now`. A request the runner
    added on the claims path is neither pinned nor reserved, and the
    approval that fills it books it, so AVAILABLE is also unfilled. The
    quote of a request that takes no claims answers canClaimNow 0 because no
    node can claim it, not because its bid is too low: such a request is
    never raised."""
    return bool(claims) and int(status) == REQUEST_AVAILABLE and int(now) <= int(created_at) + int(
        max_request_age_seconds)


def decide_raise(quote: Quote, claimers_counted: int, approvable_counted: int, claimed_in_round: bool,
                 step_now: int, max_steps: int, round_number: int, max_rounds: int,
                 ceiling_wei: Optional[int]) -> RaiseDecision:
    """Whether to raise the bid (3.10 rule 4, 3.15, D92, D23) of a request
    that takes claims (takes_claims), when the approval rule found no
    standing claim. `quote` is the reader's quote over the nodes at or above
    the minimum the runner applies, so claimers below it hold nothing back;
    `claimers_counted` is the number of claimers at or above that minimum
    and `approvable_counted` how many of their claims can be approved now.

    No claim the runner would approve can come when no counted node can
    claim at the bid in force, or every one that can has claimed and none of
    those claims can be approved; otherwise the runner waits for them. A
    quote that counted no node cannot be helped by a raise. The contract
    admits a raise while nobody claimed in the round and, once a claim was
    mined in it, from step maxSteps + 1; a request is raised at most
    maxRounds - 1 times. The bid sent is max(minBidWei, bid + 1), sent only
    within the client's ceiling, which the settings hold at most the PoX's
    bound MAX_PRICE_WEI; with no ceiling the quote is reported."""
    if quote.counted == 0 or quote.min_bid_wei == UINT256_MAX:
        return RaiseDecision(REPORT, None, "no listed node at or above the minimum score covers the request's "
                                           "resources and template: a raise cannot help")
    can_come = quote.can_claim_now > 0 and not (claimers_counted >= quote.can_claim_now and approvable_counted == 0)
    if can_come:
        return RaiseDecision(WAIT, None, f"{quote.can_claim_now} listed node(s) can claim at the bid in force")
    bid = send_bid(quote.min_bid_wei, quote.bid_wei)
    if round_number + 1 >= max_rounds:
        return RaiseDecision(REPORT, bid, f"the request has had {round_number + 1} round(s), the most a request "
                                          f"has (maxRounds {max_rounds}): its bid is not raised again")
    if ceiling_wei is None:
        return RaiseDecision(REPORT, bid, f"a listed node matches at {bid} wei per CU-hour; no bid ceiling is set, "
                                          "so the bid is not raised")
    if bid > int(ceiling_wei):
        return RaiseDecision(REPORT, bid, f"the lowest matching bid, {bid} wei per CU-hour, is above the bid "
                                          f"ceiling of {int(ceiling_wei)}")
    if claimed_in_round and step_now <= max_steps:
        return RaiseDecision(WAIT, bid, f"a claim was mined in this round: the contract admits a raise from step "
                                        f"{max_steps + 1}")
    return RaiseDecision(RAISE, bid, f"no claim can come at the bid in force; raising to {bid} wei per CU-hour")


# ------------------------------------------------------------- minimum

def minimum_score(explicit: Optional[int], dapp_minimum: Optional[int], default_class: bool, minimum_on: bool,
                  tier: Optional[int]) -> int:
    """The minimum score the runner applies to a request (3.10 rule 5, D62,
    D71, D88, D138): the one the developer or the client set, 0 included,
    as set; else the dApp's minimum operator score the image registry
    records; else, for a dApp provably of the default class, 0.50 once
    minimumOn() answers true and 0 before; else the top tier, `tier`, the
    boundary tierScore answers for the request's round (0 while it is not
    read)."""
    if explicit is not None:
        return int(explicit)
    if dapp_minimum is not None:
        return int(dapp_minimum)
    if default_class:
        return DEFAULT_MIN_SCORE if minimum_on else 0
    return int(tier or 0)


class LocalList:
    """The runner's local list (3.19, D120): from its own orders, the nodes
    whose claims it approves for no request of a dApp for LOCAL_LIST_SECONDS
    after LOCAL_LIST_ENDS of its orders of that dApp on that node ended, in
    either class, in code 20, 62, a 33 before its time, 59 or 63, all within
    LOCAL_LIST_SECONDS. Held in memory for the runner's life."""

    def __init__(self) -> None:
        self._ends: Dict[tuple, List[int]] = {}

    def record(self, image_cid: str, node, code: int, at: int, early_33: bool = False) -> None:
        """Records an order of `image_cid` on `node` that ended at `at` with
        `code`, `early_33` stating whether a code 33 was a timeout before its
        time (PoxMatching's early33); an end the list does not count is not
        kept."""
        if code not in LOCAL_LIST_CODES and not (code == CODE_TIMEOUT and early_33):
            return
        self._ends.setdefault((image_cid, address_text(node)), []).append(int(at))

    def blocked(self, image_cid: str, node, now: int) -> bool:
        """Whether no claim of `node` is approved for `image_cid` at `now`."""
        ends = sorted(t for t in self._ends.get((image_cid, address_text(node)), []) if t <= now)
        for i in range(len(ends) - LOCAL_LIST_ENDS + 1):
            window = ends[i:i + LOCAL_LIST_ENDS]
            if window[-1] - window[0] <= LOCAL_LIST_SECONDS and now - window[-1] < LOCAL_LIST_SECONDS:
                return True
        return False

    def nodes(self, image_cid: str, now: int) -> List[str]:
        """The nodes `image_cid`'s list holds at `now`."""
        return sorted(node for (image, node) in self._ends if image == image_cid and self.blocked(image, node, now))


# ------------------------------------------------------------- results

ResultFields = namedtuple("ResultFields", "landed_at ran_until sl_class")


def _field(text: str) -> Optional[int]:
    """A field in the form of spec/matching.md 17: "0", or a nonzero ASCII
    digit followed by ASCII digits; None otherwise."""
    if not text or any(c not in DIGITS for c in text) or (len(text) > 1 and text[0] == "0"):
        return None
    return int(text)


def result_fields(result: str) -> Optional[ResultFields]:
    """Fields 15 to 17 of the result string the trustedzone signed
    (spec/matching.md 17): landedAt, ranUntil and the class, each read when
    the result has 18 fields or more and each of the three is in the form
    and at most its bound; None otherwise, a result that states no class.
    Fields after 17 are not read."""
    fields = str(result).split(":")
    if len(fields) < RESULT_FIELDS_MIN:
        return None
    values = []
    for index, bound in RESULT_FIELD_BOUNDS:
        value = _field(fields[index])
        if value is None or value > bound:
            return None
        values.append(value)
    return ResultFields(*values)


# ------------------------------------------------------------- stored result

# What the stored result's grammar reads for an order (spec/matching.md 17,
# "The stored result"; result-fields.json `stored`): the status, and for a
# string that carries a transaction the order it calls for, its signer (lower
# case) and, `decoded`, the task code.
StoredRead = namedtuple("StoredRead", "status order_id code signer")
STORED_DECODED = "decoded"
STORED_NOT_V3 = "notV3"
STORED_NO_TRANSACTION = "noTransaction"
STORED_OTHER_ORDER = "otherOrder"
STORED_NO_CODE = "noCode"
# The most bytes of transaction the stored result's hex run holds.
MAX_STORED_TRANSACTION_BYTES = 4096
# Half the order of secp256k1: the highest s of a signature that is read.
SECP256K1_HALF_ORDER = 0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0
# The selector of _addResultToOrder(uint256,string).
ADD_RESULT_SELECTOR = bytes.fromhex("14e9f384")
HEX_DIGITS = frozenset(b"0123456789abcdef")


def _rlp_item(b: bytes, at: int) -> Optional[tuple]:
    """(is_list, offset, length) of the RLP item of `b` at `at` in canonical
    form, None otherwise: the short form below 56 bytes, the long form with
    no leading zero byte from 56 on, and a single byte below 0x80 written as
    itself, never as a one-byte string."""
    if at >= len(b):
        return None
    c = b[at]
    if c < 0x80:
        return False, at, 1
    is_list = c >= 0xc0
    short = c - 0xc0 if is_list else c - 0x80
    if short <= 55:
        off, length = at + 1, short
        if not is_list and length == 1 and (off >= len(b) or b[off] < 0x80):
            return None
    else:
        n = short - 55
        if at + 1 + n > len(b) or b[at + 1] == 0:
            return None
        length = int.from_bytes(b[at + 1:at + 1 + n], "big")
        if length < 56 or length > len(b):
            return None
        off = at + 1 + n
    if off + length > len(b):
        return None
    return is_list, off, length


def _rlp_list_header(length: int) -> bytes:
    """The header of an RLP list whose payload is `length` bytes."""
    if length <= 55:
        return bytes([0xc0 + length])
    size = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0xf7 + len(size)]) + size


def _rlp_integer(value: int) -> bytes:
    """The RLP item of the integer `value`: its big-endian bytes without
    leading zeros."""
    data = value.to_bytes((value.bit_length() + 7) // 8, "big") if value else b""
    if len(data) == 1 and data[0] < 0x80:
        return data
    return bytes([0x80 + len(data)]) + data


def read_stored(stored: str, order_id: int) -> StoredRead:
    """What the grammar of spec/matching.md 17 reads from the stored result
    `stored`, its UTF-8 bytes as they stand (nothing trimmed or folded), for
    order `order_id`:

        stored = "v3:" "0x" 1*( hexdig hexdig ) [ ":" rest ]

    with lower-case hex digits, an even count of them and at most 4,096
    bytes. A string that does not begin "v3:" is notV3; one outside the
    grammar, or whose run is not one canonical RLP list of the nine items of
    a legacy transaction (to empty or 20 bytes; v, r, s of at most 8, 32 and
    32 bytes; v 27, 28 or 35 and above; s at most half the curve's order)
    signed over items 0 to 5 (with the chain id, 0 and 0 for EIP-155) and
    calling exactly _addResultToOrder(orderId < 2^64, a valid UTF-8 string),
    is noTransaction. Otherwise the transaction's signer and order are read:
    otherOrder for another order, noCode when field 1 of its result string
    is not a run of ASCII digits, and decoded with that task code (at most
    2^64 - 1)."""
    s = str(stored).encode("utf-8", "surrogatepass")
    if s[:3] != b"v3:":
        return StoredRead(STORED_NOT_V3, None, None, None)
    none = StoredRead(STORED_NO_TRANSACTION, None, None, None)
    if s[3:5] != b"0x":
        return none
    end = s.find(b":", 5)
    run = s[5:] if end < 0 else s[5:end]
    if len(run) % 2 or len(run) // 2 > MAX_STORED_TRANSACTION_BYTES or any(c not in HEX_DIGITS for c in run):
        return none
    raw = bytes.fromhex(run.decode("ascii"))
    top = _rlp_item(raw, 0)
    if top is None or not top[0] or top[1] + top[2] != len(raw):
        return none
    items = []
    at = top[1]
    while at < len(raw):
        item = _rlp_item(raw, at)
        if len(items) == 9 or item is None or item[0]:
            return none
        items.append(item)
        at = item[1] + item[2]
    if len(items) != 9:
        return none

    def item_bytes(i: int) -> bytes:
        return raw[items[i][1]:items[i][1] + items[i][2]]

    if items[3][2] not in (0, 20) or items[6][2] > 8 or items[7][2] > 32 or items[8][2] > 32:
        return none
    v = int.from_bytes(item_bytes(6), "big")
    r = int.from_bytes(item_bytes(7), "big")
    sig_s = int.from_bytes(item_bytes(8), "big")
    if v >= 35:
        recid = (v - 35) % 2
        suffix = _rlp_integer((v - 35) // 2) + b"\x80\x80"
    elif v in (27, 28):
        recid = v - 27
        suffix = b""
    else:
        return none
    if sig_s > SECP256K1_HALF_ORDER:
        return none
    body = raw[top[1]:items[5][1] + items[5][2]] + suffix
    digest = keccak(_rlp_list_header(len(body)) + body)
    try:
        signer = keys.Signature(vrs=(recid, r, sig_s)).recover_public_key_from_msg_hash(digest).to_address().lower()
    except Exception:
        return none
    data = item_bytes(5)
    if len(data) < 100 or data[:4] != ADD_RESULT_SELECTOR:
        return none
    called = int.from_bytes(data[4:36], "big")
    length = int.from_bytes(data[68:100], "big")
    if called > UINT64_MAX or int.from_bytes(data[36:68], "big") != 0x40 or length > len(data):
        return none
    if len(data) != 100 + -(-length // 32) * 32 or any(data[100 + length:]):
        return none
    try:
        text = data[100:100 + length].decode("utf-8")
    except UnicodeDecodeError:
        return none
    if called != int(order_id):
        return StoredRead(STORED_OTHER_ORDER, called, None, signer)
    fields = text.split(":")
    if len(fields) < 2 or not fields[1] or any(c not in DIGITS for c in fields[1]):
        return StoredRead(STORED_NO_CODE, called, None, signer)
    return StoredRead(STORED_DECODED, called, min(int(fields[1]), UINT64_MAX), signer)


# The ends section 8 item 16 reports by class, with their names (3.19; SLH 7).
END_NAMES = {
    20: "SIGNATURE_ERROR",
    44: "TRUSTEDZONE_FAILURE",
    47: "CHAIN_UNAVAILABLE",
    59: "NETWORK_UNAVAILABLE",
    62: "SECURELOCK_SILENT",
    63: "PAYLOAD_LOST",
}
EARLY_TIMEOUT_NAME = "EXECUTION_TIMEOUT, before its time"
# The ends PoxMatching's noteAmbiguous takes (3.19): 47, 59 and 63 in every
# class, a default-class 62, and a custom class's 20 and 62; a 33 before its
# time as a 62.
AMBIGUOUS_ANY_CLASS = frozenset({47, 59, 63})
AMBIGUOUS_CUSTOM_CLASS = frozenset({20, 62})

# What section 8 item 16 tells the client of an end: its code and name, the
# class the result states (None: none), who is at fault, what is paid and
# refunded, and whether noteAmbiguous applies to it.
EndReport = namedtuple("EndReport", "code name sl_class at_fault settlement ambiguous text")


def end_report(code: int, fields: Optional[ResultFields], early_33: bool = False) -> Optional[EndReport]:
    """The report of an order that closed with code 20, 62, 44, 47, 59 or 63,
    or with a 33 before its time (`early_33`, PoxMatching's early33), which
    is settled as a 62 (section 8 item 16; 3.19); None for any other code.
    The class is the result's field 17; a result that states none is of a
    trustedzone before the release, whose 20 and 62 are paid as a valid
    result."""
    early = code == CODE_TIMEOUT and early_33
    settled = 62 if early else code
    if settled not in END_NAMES:
        return None
    name = EARLY_TIMEOUT_NAME if early else END_NAMES[code]
    silent = "33 before its time" if early else "62"
    sl_class = fields.sl_class if fields is not None else None
    if settled in (20, 62) and sl_class == DEFAULT_CLASS:
        at_fault = "operator"
        settlement = (f"the whole escrow is refunded and the node is charged; a {silent} the validators do not "
                      "charge for want of their probes is refunded with the node's chain costs paid")
    elif settled in (20, 62):
        at_fault = "developer and client" if sl_class == CUSTOM_CLASS else "not stated"
        settlement = ("the order is paid to the operator in full, at the developer's and the client's risk"
                      if sl_class == CUSTOM_CLASS else
                      "the result states no class: the order is settled as a valid result")
    elif code == 44:
        at_fault = "operator"
        settlement = "the whole escrow is refunded and the node is charged, in every class"
    elif code == 47:
        at_fault = "the network's endpoint or the operator"
        settlement = ("the work and the fees on it are refunded and the node's chain costs are paid; the node is "
                      "charged when the validators' probes show the endpoint answering")
    else:
        at_fault = "the outside service, the network or the operator" if code == 59 else "the backend or the operator"
        until = fields.ran_until if fields is not None else 0
        settlement = f"the work up to {until} (ranUntil) is paid and the work after it is refunded"
    ambiguous = settled in AMBIGUOUS_ANY_CLASS or (settled in AMBIGUOUS_CUSTOM_CLASS and sl_class == CUSTOM_CLASS) or (
        settled == 62 and sl_class == DEFAULT_CLASS)
    text = (f"The order failed with no result, task code {code} ({name}); at fault: {at_fault}; {settlement}.")
    return EndReport(code, name, sl_class, at_fault, settlement, ambiguous and fields is not None, text)


# ------------------------------------------------------------- image records

# An image's records as ECImageRegistryV4's imageRecords answers them
# (IECImageRegistryV4.ImageRecords): the kind, the default release's index,
# the network flag (D126), the enclave memory in GiB (D150) and the minimum
# operator score, set or unset, in units (D138).
ImageRecords = namedtuple("ImageRecords", "kind release network_on enclave_memory_gib min_score_set min_score")
KIND_NONE = 0
KIND_DEFAULT_RELEASE = 1
KIND_NATIVE_PYTHON = 2
KIND_CUSTOM = 3
# A default release's language (IECImageRegistryV4.DefaultRelease.language).
RELEASE_LANGUAGES = {1: "JavaScript", 2: "Python on WebAssembly"}


def dapp_minimum(records: Optional[ImageRecords]) -> Optional[int]:
    """The dApp's minimum operator score its records hold (D138): the score
    when it is set, 0 included, which switches the test off; None when it is
    unset or no records are held."""
    if records is None or not records.min_score_set:
        return None
    return int(records.min_score)


def kind_text(records: ImageRecords, language: Optional[int]) -> str:
    """The kind of an image's records in words: a default release with its
    index and language, native Python, a custom securelock."""
    if records.kind == KIND_DEFAULT_RELEASE:
        named = RELEASE_LANGUAGES.get(language, f"language {language}")
        return f"default release {records.release} ({named})"
    if records.kind == KIND_NATIVE_PYTHON:
        return "native Python"
    if records.kind == KIND_CUSTOM:
        return "a custom securelock"
    return f"kind {records.kind}"


def records_text(image_cid: str, records: ImageRecords, language: Optional[int]) -> str:
    """What the image registry shows of an image before an add (8.12): its
    kind, whether its network is on, its enclave memory and its minimum
    operator score."""
    if records.kind == KIND_NONE:
        return f"The image registry holds no records of the image {image_cid}."
    minimum = (f"{records.min_score / SCORE_UNITS_PER_POINT:.4f}" if records.min_score_set else "not set")
    return (f"The image registry records the image {image_cid} as {kind_text(records, language)}: its network is "
            f"{'on' if records.network_on else 'off'}, its enclave memory {records.enclave_memory_gib} GiB, and "
            f"its minimum operator score {minimum}.")
