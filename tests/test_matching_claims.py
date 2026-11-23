"""A request served by claims (claims.ClaimsPath; MATCHING-DESIGN.md section
8): the approval of a claim at the read of each block, the raise within the
bid ceiling over the nodes at or above the minimum, the nodes the runner
passes over (its local list, a paid class's recent counted failures), the
order that does not start (expireUnstarted) and the one that expires
(expireOrder, noteRefund), the report of an end by class and the
noteAmbiguous sent an hour after the result, and the checks before the add
(a pinned node's ban, the image's health and registry records, the quote).

The chain is a stand-in for MatchingContracts that answers from Example 1 of
3.8 (matching-rank.json `example-1`, bid 1.2 ECLD per CU-hour; its rounds
open in block 1000, one-block steps after one lead block): its list words,
and claims mined at the blocks a test names, visible from those blocks on."""
import json
import logging
from pathlib import Path

import pytest

from ethernity_cloud_runner_py import claims as claims_module
from ethernity_cloud_runner_py import matching
from ethernity_cloud_runner_py.claims import ClaimsPath, claims_settings, pinned_ban, settle_pending
from ethernity_cloud_runner_py.contract.operation.matchingContract import MatchingContracts

SPEC = Path(__file__).resolve().parent / "spec" / "matching"
RANK = json.loads((SPEC / "matching-rank.json").read_text(encoding="utf-8"))
CASE = next(c for c in RANK["ranking"] if c["name"] == "example-1")
LABELS = {label: node for node, label in RANK["labels"].items()}
N1, N2, N3, N4, N5 = (LABELS[n] for n in ("N1", "N2", "N3", "N4", "N5"))
PARAMS = CASE["parameterSets"][0]
STAMP_0 = b"\x10" * 32
STAMP_1 = b"\x11" * 32
NOW = 1795008240
SLOT = 43200
IMAGE = "QmMatchingImageA"
TEMPLATE = "ecld-nodenithy-matching"
ESCROW = 3 * 10**18
QUOTE_DEFAULT = {"counted": 5, "canClaimNow": 0, "minBidWei": 7 * 10**17, "baseNowWei": 6 * 10**17,
                 "bidWei": 65 * 10**16, "addedEscrowWei": 10**17}


def words_of():
    listed = sorted(CASE["expected"]["list"], key=lambda e: (-e["band"], e["rollIndex"]))
    base = int(CASE["expected"]["baseWei"])
    return listed, base


CLAIM_OPEN = 1


def claim_word(dp, block, step=0, rnd=0):
    packed = rnd | min(step, 9) << 4 | CLAIM_OPEN << 8
    return dp | block << 48 | NOW << 96 | packed << 128


DP = {e["node"]: e["dpRequestId"] for e in CASE["expected"]["list"]}


class FakeChain:
    """MatchingContracts as the claims path calls it, on Example 1."""

    def __init__(self, runner, block=1001, last_block=1030, claims=(), quote=None, minimum_on=False, tier=0,
                 scores=None, last_failures=None, health=None, started_at=0, approved_at=NOW - 1000):
        self.runner = runner
        self.block = block - 1
        self.last_block = last_block
        self.claims = list(claims)
        self.quote = dict(quote or QUOTE_DEFAULT)
        self._minimum_on = minimum_on
        self.tier = tier
        self.scores = scores or {}
        self.last_failures = last_failures or {}
        self.health = health or [0] * 20
        self.started_at = started_at
        self.approved_at = approved_at
        self.stamp = STAMP_0
        self.round = 0
        self.round_block = 1000
        self.sent = []
        self.quote_minimums = []
        self.refuse = set()
        self.time = NOW
        self.marked = False

    # requestInfo advances the chain by one block a read
    def request_info(self, do_request_id):
        self.block += 1
        if self.block > self.last_block:
            self.runner.running = False
        visible = [c for c in self.claims if c[1] <= self.block]
        return {"settled": True, "ranked": True, "round": self.round, "roundStamp": self.stamp,
                "seed": bytes.fromhex(CASE["expected"]["seed"][2:]), "roundBlock": self.round_block,
                "closedStep": max(0, matching.step_at(self.block + 1, self.round_block, PARAMS["stepBlocks"],
                                                      PARAMS["leadBlocks"]) - 1),
                "stepNow": matching.step_at(self.block, self.round_block, PARAMS["stepBlocks"],
                                            PARAMS["leadBlocks"]),
                "claimCount": len(visible), "claimedInRound": bool(visible)}

    def request_parameters(self, do_request_id):
        return dict(PARAMS)

    def candidate_pages(self, do_request_id, round_number, beyond=False, start=None):
        listed, base = words_of()
        entries = [matching.decode_eligible(int(e["word"], 16), int(e["priceWei"]) - base, e["rollIndex"], 1000)
                   for e in listed]
        h, found, _ = matching.list_hash_of(entries, PARAMS["maxSteps"])
        return [{"roundStamp": self.stamp, "eligible": [int(e["word"], 16) for e in listed],
                 "tips": [int(e["priceWei"]) - base for e in listed], "indexes": [e["rollIndex"] for e in listed],
                 "hOut": h, "matchFoundOut": found, "nextBand": 0, "nextFrom": 0, "done": True, "settled": True}]

    def claimers(self, do_request_id, count):
        visible = [c for c in self.claims if c[1] <= self.block][:count]
        return [(node, claim_word(DP.get(node, 999), block), approvable) for node, block, approvable in visible]

    def schedule_of(self, do_request_id):
        return {"roundStamp": self.stamp, "complete": True, "mandated": [N1, N5, N2, N3, N4],
                "canClaim": [True] * 5}

    def chain_time(self):
        return self.time

    def slot_seconds(self):
        return SLOT

    def node_standing(self, node):
        return (self.scores.get(node, matching.SCORE_MAX), 0, 0)

    def last_failure_slot(self, node):
        return self.last_failures.get(node, 0)

    def minimum_on(self):
        return self._minimum_on

    def tier_score(self, do_request_id):
        return self.tier

    def health_words(self, image):
        return list(self.health)

    def bid_quote_pages(self, do_request_id, min_score):
        self.quote_minimums.append(min_score)
        return [dict(self.quote, roundStamp=self.stamp, done=True, nextBand=0, nextFrom=0)]

    def _send(self, name, *args):
        if name in self.refuse:
            raise RuntimeError(f"execution reverted: {name}")
        self.sent.append((name,) + args)
        return "0x" + name

    def place_order(self, do_request_id, dp_request_id):
        return self._send("place_order", do_request_id, dp_request_id)

    def placed_order(self, receipt):
        return 77

    def increase_bid(self, do_request_id, bid):
        tx = self._send("increase_bid", do_request_id, bid)
        self.stamp, self.round, self.round_block = STAMP_1, 1, self.block
        return tx

    def expire_unstarted(self, order_id):
        return self._send("expire_unstarted", order_id)

    def expire_order(self, order_id):
        return self._send("expire_order", order_id)

    def note_refund(self, order_id):
        return self._send("note_refund", order_id)

    def note_ambiguous(self, order_id, hints):
        return self._send("note_ambiguous", order_id, tuple(hints))

    def order_started_at(self, order_id):
        return self.started_at

    def order_approved_at(self, order_id):
        return self.approved_at

    def order_result_at(self, order_id):
        return NOW

    def order_marked(self, order_id):
        return self.marked


class Caller:
    def __init__(self, orders):
        self.orders = orders

    def _getOrder(self, order_id):
        return self.orders[order_id]


class Protocol:
    def __init__(self, orders):
        self.orders = orders

    def caller(self):
        return Caller(self.orders)


class Approvals:
    def __init__(self, runner):
        self.runner = runner

    def set_allowance_wei(self, wei):
        self.runner.allowances.append(wei)
        return "0xallow"


class Allowance:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class Functions:
    def allowance(self, wallet, protocol):
        return Allowance(0)


class Token:
    functions = Functions()


class Wallet:
    address = "0x" + "aa" * 20


class Contract:
    def get_protocol_address(self):
        return "0x" + "bb" * 20

    def get_balance(self):
        return 10


class Runner:
    """The parts of EthernityCloudRunner the claims path uses."""

    def __init__(self, resources=None, orders=None):
        self.logger = logging.getLogger("test_matching_claims")
        self.block_time = 0
        self.running = True
        self.matching_notices = []
        self.matching_pending = []
        self.local_list = matching.LocalList()
        self.resources = resources or {"cpu": 4, "memory": 8, "storage": 40, "bandwidth": 10, "duration": 1,
                                       "max_price_per_cu_hour_wei": 65 * 10**16, "escrow_wei": ESCROW,
                                       "max_gflops": 400, "required_gflops": 250}
        self.trustedZoneImage = TEMPLATE
        self.securelock_enclave = "matching-dapp"
        self.protocol_contract = Protocol(orders or {})
        self.signer = Wallet()
        self.contract = Contract()
        self.token_contract = Token()
        self.allowances = []
        self.network_config = type("Entry", (), {"TOKEN_NAME": "tECLD"})

    def is_running(self):
        return self.running

    def is_unsafe(self):
        return False

    def poll_transaction(self, tx, max_attempts=10):
        return {"status": 1, "logs": []}

    def _read_before_request(self, read):
        return read()

    def _sender(self):
        return Approvals(self)

    def _matching_notice(self, text, level=logging.WARNING):
        self.matching_notices.append(text)


def path_of(runner, chain, **settings):
    resources = dict(runner.resources, **settings)
    path = ClaimsPath(runner, chain, claims_settings(resources))
    path.image_cid = IMAGE
    return path


# ------------------------------------------------------------- the approval

def test_the_mandated_node_s_claim_is_approved_at_the_read_of_its_step():
    runner = Runner()
    chain = FakeChain(runner, claims=[(N1, 1002, True)])
    order = path_of(runner, chain).await_approval(301, 600)
    assert order == 77
    assert chain.sent == [("place_order", 301, DP[N1])]
    assert chain.block == 1002


def test_an_in_time_claim_is_taken_before_a_late_one():
    runner = Runner()
    chain = FakeChain(runner, block=1003, claims=[(N1, 1003, True), (N5, 1003, True)])
    assert path_of(runner, chain).await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N5])]


def test_an_early_claim_waits_for_the_steps_before_it():
    runner = Runner()
    chain = FakeChain(runner, block=1001, claims=[(N3, 1001, True)])
    assert path_of(runner, chain).await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N3])]
    assert chain.block == 1004


def test_a_claim_below_the_minimum_does_not_stand():
    runner = Runner()
    chain = FakeChain(runner, claims=[(N1, 1001, True), (N5, 1001, True)], scores={N1: 4999})
    assert path_of(runner, chain, min_node_score=0.5).await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N5])]
    assert chain.block == 1002


def test_with_no_setting_a_paid_class_applies_the_top_tier():
    runner = Runner()
    chain = FakeChain(runner, claims=[(N1, 1001, True), (N5, 1001, True)], scores={N1: 20_000}, tier=24_000)
    assert path_of(runner, chain).await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N5])]


def test_a_default_class_applies_0_50_once_the_switch_is_on():
    runner = Runner()
    chain = FakeChain(runner, claims=[(N1, 1001, True), (N5, 1001, True)], scores={N1: 4999}, minimum_on=True)
    path = path_of(runner, chain)
    path.default_class = True
    assert path.await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N5])]
    runner = Runner()
    chain = FakeChain(runner, claims=[(N1, 1001, True), (N5, 1001, True)], scores={N1: 4999}, minimum_on=False)
    path = path_of(runner, chain)
    path.default_class = True
    assert path.await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N1])]


def test_a_recent_failed_order_passes_the_claim_over():
    runner = Runner()
    chain = FakeChain(runner, claims=[(N1, 1001, True), (N5, 1001, True)], last_failures={N1: NOW // SLOT - 3})
    assert path_of(runner, chain).await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N5])]


def test_a_node_of_the_local_list_is_passed_over():
    runner = Runner()
    runner.local_list.record(IMAGE, N1, 62, NOW - 7200)
    runner.local_list.record(IMAGE, N1, 59, NOW - 3600)
    chain = FakeChain(runner, claims=[(N1, 1001, True), (N5, 1001, True)])
    assert path_of(runner, chain).await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N5])]


def test_a_paid_class_passes_over_the_node_of_a_recent_counted_failure():
    runner = Runner(orders={40: ("0x" + "cc" * 20, N1, 300, 501, 2)})
    health = [0] * 20
    health[3] = 40 | 7 << 48 | 9 << 96 | (NOW // 86_400) << 144
    chain = FakeChain(runner, claims=[(N1, 1001, True), (N5, 1001, True)], health=health)
    assert path_of(runner, chain).await_approval(301, 600) == 77
    assert chain.sent == [("place_order", 301, DP[N5])]


def test_an_approval_the_call_refuses_is_left_for_the_next_read():
    runner = Runner()
    chain = FakeChain(runner, last_block=1004, claims=[(N1, 1002, True)])
    chain.refuse.add("place_order")
    assert path_of(runner, chain).await_approval(301, 600) is None
    assert chain.sent == []


# ------------------------------------------------------------- the raise

def test_no_claim_can_come_raises_within_the_ceiling():
    runner = Runner()
    chain = FakeChain(runner, last_block=1008)
    path = path_of(runner, chain, max_bid_per_cu_hour_wei=10**18)
    assert path.await_approval(301, 600) is None
    assert ("increase_bid", 301, 7 * 10**17) in chain.sent
    assert runner.allowances == [10**17]
    assert chain.quote_minimums and set(chain.quote_minimums) == {0}


def test_the_quote_runs_over_the_minimum_the_runner_applies():
    runner = Runner()
    chain = FakeChain(runner, last_block=1011, claims=[(N1, 1001, True)], scores={N1: 100})
    path_of(runner, chain, max_bid_per_cu_hour_wei=10**18, min_node_score=0.5).await_approval(301, 600)
    assert set(chain.quote_minimums) == {5000}
    assert ("increase_bid", 301, 7 * 10**17) in chain.sent
    assert any("below the minimum node score" in n for n in runner.matching_notices)


def test_without_a_ceiling_the_quote_is_reported_and_nothing_is_raised():
    runner = Runner()
    chain = FakeChain(runner, last_block=1008)
    path_of(runner, chain).await_approval(301, 600)
    assert not any(s[0] == "increase_bid" for s in chain.sent)
    assert any("no bid ceiling is set" in n for n in runner.matching_notices)


def test_a_quote_above_the_ceiling_is_not_sent():
    runner = Runner()
    chain = FakeChain(runner, last_block=1008)
    path_of(runner, chain, max_bid_per_cu_hour_wei=69 * 10**16).await_approval(301, 600)
    assert not any(s[0] == "increase_bid" for s in chain.sent)
    assert any("above the bid ceiling" in n for n in runner.matching_notices)


def test_nodes_that_can_still_claim_hold_the_raise():
    runner = Runner()
    chain = FakeChain(runner, last_block=1008, quote=dict(QUOTE_DEFAULT, canClaimNow=2))
    path_of(runner, chain, max_bid_per_cu_hour_wei=10**18).await_approval(301, 600)
    assert not any(s[0] == "increase_bid" for s in chain.sent)


def test_after_a_claim_in_the_round_the_raise_waits_for_step_max_steps_plus_one():
    runner = Runner()
    chain = FakeChain(runner, last_block=1012, claims=[(N1, 1001, False)])
    path_of(runner, chain, max_bid_per_cu_hour_wei=10**18).await_approval(301, 600)
    raises = [s for s in chain.sent if s[0] == "increase_bid"]
    assert raises == [("increase_bid", 301, 7 * 10**17)]
    assert matching.step_at(chain.round_block, 1000, 1, 1) == PARAMS["maxSteps"] + 1


def test_the_quote_is_read_again_after_a_raise():
    runner = Runner()
    chain = FakeChain(runner, last_block=1013)
    path_of(runner, chain, max_bid_per_cu_hour_wei=10**18).await_approval(301, 600)
    raised_at = [i for i, s in enumerate(chain.sent) if s[0] == "increase_bid"]
    assert len(raised_at) >= 2
    assert len(chain.quote_minimums) >= 2


def test_decide_raise_counts_rounds():
    quote = matching.Quote(STAMP_0, 5, 0, 7 * 10**17, 6 * 10**17, 65 * 10**16, 10**17)
    assert matching.decide_raise(quote, 0, 0, False, 1, 8, 3, 5, 10**18).action == matching.RAISE
    assert matching.decide_raise(quote, 0, 0, False, 1, 8, 4, 5, 10**18).action == matching.REPORT


def test_decide_raise_with_no_node_counted_reports():
    quote = matching.Quote(STAMP_0, 0, 0, matching.UINT256_MAX, 6 * 10**17, 65 * 10**16, 0)
    decision = matching.decide_raise(quote, 0, 0, False, 1, 8, 0, 5, 10**18)
    assert decision.action == matching.REPORT and "cannot help" in decision.reason


# ------------------------------------------------------------- the order

def test_an_order_not_started_after_900_s_is_expired_unstarted():
    runner = Runner()
    chain = FakeChain(runner, approved_at=NOW - 901)
    path = path_of(runner, chain)
    path.params = dict(PARAMS)
    started, fault = path.start_check(77)
    assert not started and "did not start within 900 s" in fault
    assert chain.sent == [("expire_unstarted", 77)]


def test_an_order_inside_its_900_s_or_started_is_left_alone():
    runner = Runner()
    chain = FakeChain(runner, approved_at=NOW - 900)
    path = path_of(runner, chain)
    path.params = dict(PARAMS)
    assert path.start_check(77) == (False, None)
    chain.started_at = NOW - 10
    chain.approved_at = NOW - 5000
    assert path.start_check(77) == (True, None)
    assert chain.sent == []


def test_expire_unstarted_follows_its_setting():
    runner = Runner()
    chain = FakeChain(runner, approved_at=NOW - 5000)
    path = path_of(runner, chain, expire_unstarted=False)
    path.params = dict(PARAMS)
    assert path.start_check(77) == (False, None)
    assert chain.sent == []


def test_an_expired_order_is_noted_for_a_refund():
    runner = Runner()
    chain = FakeChain(runner)
    path_of(runner, chain).expired(77)
    assert chain.sent == [("expire_order", 77), ("note_refund", 77)]


def test_an_expiry_the_pox_does_not_admit_yet_waits_for_settle():
    runner = Runner()
    chain = FakeChain(runner)
    chain.refuse.add("expire_order")
    path_of(runner, chain, note_refund=False).expired(77)
    assert chain.sent == [] and len(runner.matching_pending) == 1
    chain.refuse.clear()
    settle_pending(runner)
    assert chain.sent == [("expire_order", 77)] and runner.matching_pending == []


def result_with(code, fields):
    return ":".join(["v6", str(code)] + ["x"] * 13 + fields)


def test_a_custom_class_62_is_reported_paid_and_noted_an_hour_later():
    runner = Runner()
    chain = FakeChain(runner)
    path = path_of(runner, chain)
    path.hints = [1, 2, 3]
    report = path.after_result(77, N1, 62, result_with(62, ["0", "0", "0"]))
    assert report.at_fault == "developer and client" and "paid to the operator" in report.text
    assert runner.matching_pending[0]["kind"] == "note"
    settle_pending(runner)
    assert chain.sent == [] and len(runner.matching_pending) == 1
    chain.time = NOW + 3600
    settle_pending(runner)
    assert chain.sent == [("note_ambiguous", 77, (1, 2, 3))] and runner.matching_pending == []


def test_a_noted_end_is_not_noted_again():
    runner = Runner()
    chain = FakeChain(runner)
    path_of(runner, chain).after_result(77, N1, 47, result_with(47, ["10", "0", "1"]))
    chain.time = NOW + 3600
    chain.marked = True
    settle_pending(runner)
    assert chain.sent == [] and runner.matching_pending == []


def test_a_default_class_20_is_the_operator_s_and_not_noted():
    runner = Runner()
    chain = FakeChain(runner)
    report = path_of(runner, chain).after_result(77, N1, 20, result_with(20, ["0", "0", "1"]))
    assert report.at_fault == "operator" and "whole escrow is refunded" in report.text
    assert runner.matching_pending == []


def test_an_end_the_local_list_counts_is_recorded():
    runner = Runner()
    chain = FakeChain(runner)
    path = path_of(runner, chain)
    path.after_result(77, N1, 62, result_with(62, ["0", "0", "0"]))
    assert not runner.local_list.blocked(IMAGE, N1, NOW)
    path.after_result(78, N1, 63, result_with(63, ["0", "100", "0"]))
    assert runner.local_list.blocked(IMAGE, N1, NOW)
    assert not runner.local_list.blocked(IMAGE, N1, NOW + matching.LOCAL_LIST_SECONDS)
    path.after_result(79, N2, 0, result_with(0, ["0", "0", "0"]))
    assert not runner.local_list.blocked(IMAGE, N2, NOW)


def test_the_report_of_each_code():
    custom = matching.ResultFields(0, 0, 0)
    default = matching.ResultFields(0, 0, 1)
    assert matching.end_report(44, custom).at_fault == "operator"
    assert "chain costs are paid" in matching.end_report(47, custom).settlement
    assert "up to 1234" in matching.end_report(59, matching.ResultFields(0, 1234, 0)).settlement
    assert "up to 99" in matching.end_report(63, matching.ResultFields(0, 99, 1)).settlement
    assert matching.end_report(62, default).ambiguous and matching.end_report(62, custom).ambiguous
    assert not matching.end_report(20, default).ambiguous and matching.end_report(20, custom).ambiguous
    assert not matching.end_report(62, None).ambiguous
    assert "states no class" in matching.end_report(20, None).settlement
    assert matching.end_report(0, custom) is None and matching.end_report(37, custom) is None


def test_hints_name_three_matching_nodes_of_the_round():
    listed, base = words_of()
    entries = [matching.decode_eligible(int(e["word"], 16), 0, e["rollIndex"], 1000) for e in listed]
    hints = claims_module.hint_words(entries)
    assert len(hints) == 3
    for hint, e in zip(hints, [e for e in entries if e.match][:3]):
        assert hint >> 80 == e.band and (hint >> 48) & (2**32 - 1) == e.index
        assert (hint >> 24) & (2**24 - 1) == e.listed_ordinal
    assert claims_module.hint_words(entries[:2]) == []


# ------------------------------------------------------------- before the add

class Images(FakeChain):
    def __init__(self, runner, health=(0, 0, 0, 0, False), records=None, template_word=0, quote=None):
        super().__init__(runner)
        self.health_answer = health
        self.records = records or {"registry": None, "default_release": False, "session": b"\x00" * 32,
                                   "latest": b"\x00" * 32, "current_image": None}
        self.template_word = template_word
        self.quote_for = quote or {"counted": 5, "minBidWei": 7 * 10**17, "baseNowWei": 6 * 10**17}
        self.quotes_for = []

    def template(self, name):
        return matching.decode_template(self.template_word)

    def image_health(self, image):
        return self.health_answer

    def image_records(self, image_cid):
        return self.records

    def bid_quote_for(self, terms, template_name, min_score):
        self.quotes_for.append((terms, template_name, min_score))
        return self.quote_for


def test_a_marked_image_is_refused_unless_allowed():
    runner = Runner()
    chain = Images(runner, health=(1, 6, 3, 3, True))
    with pytest.raises(ValueError, match="marked likely broken"):
        path_of(runner, chain).check_before_add(IMAGE, TEMPLATE)
    path_of(runner, chain, allow_marked_image=True).check_before_add(IMAGE, TEMPLATE)
    assert any("allow_marked_image is set" in n for n in runner.matching_notices)


def test_an_image_with_no_counted_order_is_told():
    runner = Runner()
    path_of(runner, Images(runner)).check_before_add(IMAGE, TEMPLATE)
    assert any("no counted order" in n for n in runner.matching_notices)


def test_a_superseded_image_is_refused_naming_the_current_one():
    runner = Runner()
    records = {"registry": "0x1", "default_release": True, "session": b"\x01" * 32, "latest": b"\x02" * 32,
               "current_image": "QmCurrent"}
    with pytest.raises(ValueError, match="QmCurrent"):
        path_of(runner, Images(runner, records=records)).check_before_add(IMAGE, TEMPLATE)


def test_the_class_is_default_only_on_a_marked_template_with_the_newest_session():
    marked = 1 << 40 | 1 << 48
    records = {"registry": "0x1", "default_release": True, "session": b"\x01" * 32, "latest": b"\x01" * 32,
               "current_image": None}
    runner = Runner()
    path = path_of(runner, Images(runner, records=records, template_word=marked))
    path.check_before_add(IMAGE, TEMPLATE)
    assert path.default_class and path.envelope == matching.ENVELOPE_CHUNKED
    runner = Runner()
    path = path_of(runner, Images(runner, records=records, template_word=0))
    path.check_before_add(IMAGE, TEMPLATE)
    assert not path.default_class and path.envelope == matching.ENVELOPE_WHOLE_PASS
    runner = Runner()
    path = path_of(runner, Images(runner, records=dict(records, default_release=False), template_word=marked),
                   min_node_score=0.2)
    path.check_before_add(IMAGE, TEMPLATE)
    assert not path.default_class
    assert any("paid to the operator at the client's risk" in n for n in runner.matching_notices)


def test_the_quote_before_the_add_takes_the_request_s_terms():
    runner = Runner()
    chain = Images(runner)
    path_of(runner, chain).check_before_add(IMAGE, TEMPLATE)
    terms, template, minimum = chain.quotes_for[0]
    assert (terms["needGflops"], terms["ceilGflops"], terms["hours"]) == (250, 400, 1)
    assert template == TEMPLATE and minimum == 0
    assert any("lowest bid at which a listed node matches is 700000000000000000" in n
               for n in runner.matching_notices)


def test_a_pinned_node_s_ban_is_told_with_its_end():
    class Banned(FakeChain):
        def node_standing(self, node):
            return (0, 0, NOW + 3600)
    assert "banned until" in pinned_ban(Banned(Runner()), N1)
    assert pinned_ban(FakeChain(Runner()), N1) is None


def test_a_request_without_v2_terms_is_refused_before_anything_is_sent():
    with pytest.raises(ValueError, match="max_price_per_cu_hour_wei"):
        claims_settings({"cpu": 1})
    with pytest.raises(ValueError, match="whole number"):
        claims_settings({"max_price_per_cu_hour_wei": 1, "escrow_wei": 1, "max_gflops": -1})
    settings = claims_settings({"max_price_per_cu_hour_wei": 1, "escrow_wei": 2})
    assert settings.min_score is None and settings.recent_failure_slots == 14
    assert settings.expire_unstarted and settings.note_refund and settings.note_ambiguous
    assert not settings.allow_marked_image and settings.max_bid_wei is None


# ------------------------------------------------------------- sends

class Fn:
    def __init__(self, reverts):
        self.reverts = reverts
        self.calls = []

    def call(self, params):
        self.calls.append(params)
        if self.reverts:
            raise RuntimeError("execution reverted")


class Sender:
    def __init__(self):
        self.signer = Wallet()
        self.sent = []

    def _build_sign_send(self, fn, gas):
        self.sent.append((fn, gas))
        return "0xhash"


def test_a_send_is_made_as_a_call_first():
    contracts = MatchingContracts.__new__(MatchingContracts)
    contracts.contract = Sender()
    fn = Fn(reverts=False)
    assert contracts._send(fn, "_placeOrder") == "0xhash"
    assert fn.calls == [{"from": Wallet.address}] and contracts.contract.sent == [(fn, 1_500_000)]
    refused = Fn(reverts=True)
    with pytest.raises(RuntimeError):
        contracts._send(refused, "increaseBid")
    assert len(contracts.contract.sent) == 1
