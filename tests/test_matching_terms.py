"""The terms a runner adds a V2 request with, and the reads around them, on
the spec copies of tests/spec/ (MATCHING-SYNC-PLAN.md 4.4, RUN-03 to
RUN-14):

- the PoX's generation, read from the chain (VERSION() for the add's form,
  the pricing's matching() for the claims path; OD18), and the add in each
  form ("2.0" maxGflops uint48, "1.2" uint32);
- the minimum EPC max(1, imageEpcUnits(image), client) in bits 32 to 47 of
  every "2.0" add, the quote and the escrow (D200; OD23), and the memory
  need max(client, the image's enclave memory) (8.12);
- the PoX's bounds tested before anything is sent (bid and bid ceiling 1 to
  2^128 - 1, gasLevel 1e18 to 2^128 - 1, the required GFLOPS at most the
  ceiling, metadata at most 2,048 bytes) and one instance (OD25);
- no raise and no approval on a request that takes no claims, a request
  whose set has claims off served without claims (8.4, item 23);
- a request with V2 terms while claims are off (OD26) and no score test on
  it (D196); one set of defaults with runner-js (0, 0, 1e18; resource 0;
  the score's rounding);
- receipts judged by their status; the securelock's own session.

No chain: the contracts are stand-ins."""
from types import SimpleNamespace

import pytest
import requests
from eth_utils import keccak
from web3.exceptions import ContractLogicError

from ethernity_cloud_runner_py import claims as claims_module
from ethernity_cloud_runner_py import matching
from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.claims import ClaimsPath, TermedRequest, claims_settings, settle_pending, v2_settings
from ethernity_cloud_runner_py.contract.abi import matchingAbi
from ethernity_cloud_runner_py.contract.operation import matchingContract
from ethernity_cloud_runner_py.contract.operation.matchingContract import (NO_GENERATION, MatchingContracts,
                                                                           PoxGeneration, read_generation,
                                                                           send_v2_add)
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

from test_matching_claims import (DP, ESCROW, IMAGE, N1, NOW, PARAMS, QUOTE_DEFAULT, TEMPLATE, Deployed, FakeChain,
                                  Images, Runner, contracts_with, path_of, records_of)
from spec_copies import load

RANK = load("matching-rank.json")
QUOTES = {case["name"]: case for case in RANK["quotes"]}
PROTOCOL = "0x" + "bb" * 20
PRICING = "0x" + "0c" * 20
MATCHING = "0x" + "01" * 20
ZERO = "0x" + "00" * 20
REVERT = ContractLogicError("execution reverted")
V2 = {"cpu": 1, "memory": 1, "storage": 1, "bandwidth": 1, "duration": 1, "validators": 1,
      "max_price_per_cu_hour_wei": 10**18, "escrow_wei": 3 * 10**18}


# ------------------------------------------------------------- the generation

class _Call:
    def __init__(self, answer):
        self.answer = answer

    def call(self, *args):
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


class _Functions:
    def __init__(self, answers, reads):
        self.answers, self.reads = answers, reads

    def __getattr__(self, name):
        def function(*args):
            self.reads.append(name)
            return _Call(self.answers[name])
        return function


class _Chain:
    """A provider whose contracts answer from `answers` by address and
    function name, each read kept in `reads`."""

    def __init__(self, answers):
        self.answers = answers
        self.reads = []
        self.eth = SimpleNamespace(contract=self.contract)

    def contract(self, address, abi):
        return SimpleNamespace(functions=_Functions(self.answers[address.lower()], self.reads), address=address,
                               abi=abi)


def _protocol(answers):
    return SimpleNamespace(provider=_Chain(answers), protocol_address=PROTOCOL)


def test_a_2_0_pox_whose_pricing_names_a_pox_matching():
    contract = _protocol({PROTOCOL: {"VERSION": "2.0", "pricingAddress": PRICING}, PRICING: {"matching": MATCHING}})
    assert read_generation(contract) == PoxGeneration("2.0", MATCHING, PRICING)
    assert contract.provider.reads == ["VERSION", "pricingAddress", "matching"]


def test_a_1_2_pox_whose_pricing_answers_no_matching():
    contract = _protocol({PROTOCOL: {"VERSION": "1.2", "pricingAddress": PRICING}, PRICING: {"matching": REVERT}})
    assert read_generation(contract) == PoxGeneration("1.2", ZERO, PRICING)


@pytest.mark.parametrize("version", ["1.1", REVERT])
def test_a_pox_that_takes_no_v2_add_reads_no_pricing(version):
    contract = _protocol({PROTOCOL: {"VERSION": version}})
    assert read_generation(contract) == PoxGeneration(None if version is REVERT else version, ZERO)
    assert contract.provider.reads == ["VERSION"]


def test_a_generation_read_the_rpc_does_not_answer_is_raised():
    contract = _protocol({PROTOCOL: {"VERSION": requests.exceptions.ConnectionError("no answer")}})
    with pytest.raises(requests.exceptions.ConnectionError):
        read_generation(contract)
    contract = _protocol({PROTOCOL: {"VERSION": "2.0", "pricingAddress": PRICING},
                          PRICING: {"matching": requests.exceptions.ReadTimeout("no answer")}})
    with pytest.raises(requests.exceptions.ReadTimeout):
        read_generation(contract)


class _Add:
    def __init__(self, sent, abi):
        self.sent, self.abi = sent, abi
        self.functions = self

    def addDORequestV2(self, *args):
        self.sent.append(("built", self.abi, args))
        return SimpleNamespace(call=lambda params: self.sent.append(("call", params)))


def _sender():
    sent = []
    contract = SimpleNamespace(protocol_address=PROTOCOL, signer=SimpleNamespace(address="0x" + "aa" * 20))
    contract.provider = SimpleNamespace(eth=SimpleNamespace(contract=lambda address, abi: _Add(sent, abi)))
    contract._build_sign_send = lambda fn, gas: sent.append(("send", gas)) or "0xadd"
    return contract, sent


TERMS = {"cpu": 1, "memory": 2, "storage": 3, "bandwidth": 4, "duration": 5}
WORD = 3 << 32 | 250 << 16 | 400


@pytest.mark.parametrize("version,abi,word", [("2.0", matchingAbi.pox, WORD), ("1.2", matchingAbi.pox_1_2,
                                                                               WORD & matching.UINT32_MAX)])
def test_the_v2_add_takes_the_form_its_version_names(version, abi, word):
    contract, sent = _sender()
    assert send_v2_add(contract, version, TERMS, 7, WORD, 2, 10**18, ["m1", "m2", "m3", ""]) == "0xadd"
    assert sent[0] == ("built", abi, (1, 2, 3, 4, 5, 1, 7, word, 2, 10**18, "m1", "m2", "m3", ""))
    assert sent[1] == ("call", {"from": "0x" + "aa" * 20})
    assert sent[2] == ("send", matchingContract.GAS_FLOOR["addDORequestV2"])


def test_the_runner_reads_the_generation_from_the_chain_and_nothing_on_a_token_pox(monkeypatch):
    reads = []
    monkeypatch.setattr(runner_module, "read_generation", lambda contract: reads.append(contract) or
                        PoxGeneration("2.0", ZERO))
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    assert runner._read_generation() == PoxGeneration("2.0", ZERO) and len(reads) == 1
    assert EthernityCloudRunner("BLOXBERG", "MAINNET")._read_generation() == NO_GENERATION and len(reads) == 1


# ------------------------------------------------------------- V2 terms, claims off

def _runner_on(version, matching_address=ZERO):
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner._generation = PoxGeneration(version, matching_address)
    return runner


@pytest.mark.parametrize("version", ["2.0", "1.2"])
def test_v2_terms_with_an_escrow_are_added_with_terms_while_claims_are_off(version):
    termed = _runner_on(version)._termed_request(V2)
    assert isinstance(termed, TermedRequest) and termed.version == version
    assert termed.settings.bid_wei == 10**18 and termed.settings.escrow_wei == 3 * 10**18


@pytest.mark.parametrize("version", [None, "1.1"])
def test_v2_terms_on_a_pox_that_takes_no_v2_add_are_refused(version):
    with pytest.raises(ValueError, match="takes no addDORequestV2"):
        _runner_on(version)._termed_request(V2)


def test_v2_terms_without_an_escrow_or_none_at_all_are_added_without_terms():
    runner = _runner_on("2.0")
    assert runner._termed_request({k: v for k, v in V2.items() if k != "escrow_wei"}) is None
    assert any("without escrow_wei" in n for n in runner.matching_notices)
    assert _runner_on("2.0")._termed_request({"cpu": 1, "taskPrice": 2}) is None
    with pytest.raises(ValueError, match="needs the task setting max_price_per_cu_hour_wei"):
        _runner_on("2.0")._termed_request({"escrow_wei": 3})


def test_the_path_is_the_claims_path_else_the_termed_request(monkeypatch):
    monkeypatch.setattr(runner_module, "read_generation", lambda contract: PoxGeneration("2.0", ZERO))
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner._choose_path(V2, "")
    assert runner._claims is None and isinstance(runner._termed, TermedRequest)
    runner._choose_path({"cpu": 1}, "")
    assert runner._claims is None and runner._termed is None


class _NoScore(FakeChain):
    """A network's MatchingContracts whose score and records reads fail the
    case."""

    def image_records(self, image_cid):
        raise AssertionError("the image's records were read for a request not served by claims")

    def node_standing(self, node):
        raise AssertionError("a score was read for a request not served by claims")

    def minimum_on(self):
        raise AssertionError("minimumOn was read for a request not served by claims")


def test_a_termed_request_states_its_epc_minimum_and_reads_no_score(monkeypatch):
    runner = Runner(resources=dict(V2, epc_mib=200))
    chain = _NoScore(runner)
    chain.epc_need = 2
    termed = TermedRequest(runner, "2.0", chain, v2_settings(runner.resources))
    termed.check_escrow(IMAGE)
    assert termed.epc_units == 4 and chain.epc_reads == [IMAGE]
    assert runner.allowances == [3 * 10**18]
    added = []
    runner._sender = lambda: "the sender"
    monkeypatch.setattr(claims_module, "send_v2_add", lambda *args: added.append(args) or "0xadd")
    assert termed.add_request(["a", "b", "c", ""]) == "0xadd"
    assert added[0][:2] == ("the sender", "2.0") and added[0][4] == 4 << 32


def test_a_termed_request_without_pox_matching_states_one_unit_and_a_1_2_pox_none():
    runner = Runner(resources=dict(V2))
    termed = TermedRequest(runner, "2.0", None, v2_settings(runner.resources))
    termed.check_escrow(IMAGE)
    assert termed.epc_units == 1
    runner = Runner(resources=dict(V2, epc_mib=640))
    termed = TermedRequest(runner, "1.2", None, v2_settings(runner.resources))
    termed.check_escrow(IMAGE)
    assert termed.epc_units == 0 and any("epc_mib is not sent" in n for n in runner.matching_notices)


def test_a_termed_request_whose_registry_does_not_answer_is_refused_before_the_approval():
    runner = Runner(resources=dict(V2))
    chain = FakeChain(runner)
    chain.epc_need = requests.exceptions.ConnectionError("no answer")
    with pytest.raises(ValueError, match="did not answer the EPC need"):
        TermedRequest(runner, "2.0", chain, v2_settings(runner.resources)).check_escrow(IMAGE)
    assert runner.allowances == []


def test_a_termed_request_s_balance_is_checked_in_wei():
    runner = Runner(resources=dict(V2, escrow_wei=11 * 10**18))
    with pytest.raises(ValueError, match="Insufficient wallet balance"):
        TermedRequest(runner, "2.0", None, v2_settings(runner.resources)).check_balance()
    runner = Runner(resources=dict(V2, escrow_wei=10 * 10**18))
    TermedRequest(runner, "2.0", None, v2_settings(runner.resources)).check_balance()


def test_the_termed_request_is_added_with_its_metadata_and_the_metadata_bound(monkeypatch):
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.resources = V2
    runner.running = True
    sent = []
    eth = SimpleNamespace(get_transaction_receipt=lambda tx_hash: {"status": 1})
    runner.contract = SimpleNamespace(add_do_request=lambda *args: sent.append(("legacy",) + args) or "0x1",
                                      get_provider=lambda: SimpleNamespace(eth=eth))
    log = SimpleNamespace(args=SimpleNamespace(_rowNumber=12))
    event = SimpleNamespace(process_receipt=lambda receipt, errors: [log])
    runner.protocol_contract = SimpleNamespace(events=SimpleNamespace(_addDORequestEV=lambda: event))
    runner._termed = SimpleNamespace(add_request=lambda metadata: sent.append(("termed", metadata)) or "0x1")
    assert runner.create_do_request("i" * 2048, "code", "input", "") is True
    assert sent == [("termed", ["i" * 2048, "code", "input", ""])]
    with pytest.raises(ValueError, match="metadata1 of the request is 2049 bytes"):
        runner.create_do_request("i" * 2049, "code", "input", "")
    with pytest.raises(ValueError, match="metadata3 of the request is 2050 bytes"):
        runner.create_do_request("image", "code", "é" * 1025, "")
    assert len(sent) == 1


# ------------------------------------------------------------- EPC and memory

def test_the_epc_figure_is_rounded_up_to_units_of_64_mib():
    assert [matching.epc_units_of_mib(m) for m in (0, 1, 64, 65, 128, 65_535 * 64)] == [0, 1, 1, 2, 2, 65_535]
    with pytest.raises(ValueError, match="at most 4194240 MiB"):
        matching.epc_units_of_mib(65_535 * 64 + 1)
    assert matching.minimum_epc(0, 0) == 1 and matching.minimum_epc(3, 2) == 3 and matching.minimum_epc(1, 9) == 9


def test_the_claims_path_states_the_epc_minimum_in_the_quote_the_escrow_and_the_add():
    runner = Runner()
    chain = Images(runner)
    chain.epc_need = 3
    path = path_of(runner, chain, epc_mib=100)
    path.check_before_add(IMAGE, TEMPLATE)
    assert path.epc_units == 3 and chain.epc_reads == [IMAGE]
    assert chain.quotes_for[0][0]["epcUnits"] == 3
    path.check_escrow(f"v3:{IMAGE}:{TEMPLATE}")
    assert chain.escrow_reads[0][2] == 3 << 32 | 250 << 16 | 400
    added = []
    chain.add_do_request_v2 = lambda *args: added.append(args) or "0xadd"
    path.add_request(["a", "b", "c", ""])
    assert added[0][2] == 3 << 32 | 250 << 16 | 400
    assert any("minimum EPC of 3 units of 64 MiB" in n for n in runner.matching_notices)


def test_the_client_s_epc_above_the_image_s_and_one_unit_by_default():
    runner = Runner()
    chain = Images(runner)
    chain.epc_need = 3
    path = path_of(runner, chain, epc_mib=1000)
    path.check_before_add(IMAGE, TEMPLATE)
    assert path.epc_units == 16
    runner = Runner()
    path = path_of(runner, Images(runner))
    path.check_before_add(IMAGE, TEMPLATE)
    assert path.epc_units == 1 and path.max_gflops() >> 32 == 1


def test_a_registry_that_does_not_answer_the_epc_need_refuses_before_anything_is_sent():
    runner = Runner()
    chain = Images(runner)
    chain.epc_need = requests.exceptions.ConnectionError("no answer")
    with pytest.raises(ValueError, match="did not answer the EPC need"):
        path_of(runner, chain).check_before_add(IMAGE, TEMPLATE)
    assert chain.sent == [] and runner.allowances == [] and chain.quotes_for == []


def test_the_epc_need_is_read_from_the_registry_pox_matching_names():
    registry = "0x" + "03" * 20
    images = Deployed(registry, {"imageEpcUnits": 7})
    contracts = contracts_with({"imageRegistry": registry}, deployed={registry: images})
    assert contracts.image_epc_units(IMAGE) == 7 and ("imageEpcUnits", IMAGE) in images.calls
    assert contracts_with({"imageRegistry": ZERO}).image_epc_units(IMAGE) == 0


def test_the_memory_need_is_the_image_s_enclave_memory_when_it_is_larger():
    runner = Runner()
    chain = Images(runner, records=records_of(matching.KIND_CUSTOM, memory=16))
    path = path_of(runner, chain)
    path.check_before_add(IMAGE, TEMPLATE)
    assert path.memory_gb == 16 and chain.quotes_for[0][0]["memGB"] == 16
    added = []
    chain.add_do_request_v2 = lambda *args: added.append(args) or "0xadd"
    path.add_request(["a", "b", "c", ""])
    assert added[0][0]["memory"] == 16
    assert any("records an enclave memory of 16 GiB, above the request's memory of 8 GB" in n
               for n in runner.matching_notices)
    runner = Runner()
    chain = Images(runner, records=records_of(matching.KIND_CUSTOM, memory=4))
    path = path_of(runner, chain)
    path.check_before_add(IMAGE, TEMPLATE)
    assert path.memory_gb == 8 and chain.quotes_for[0][0]["memGB"] == 8
    assert not any("records an enclave memory" in n for n in runner.matching_notices)


# ------------------------------------------------------------- bounds

@pytest.mark.parametrize("key,value,message", [
    ("max_price_per_cu_hour_wei", 2**128, "max_price_per_cu_hour_wei must be 1 to"),
    ("max_bid_per_cu_hour_wei", 0, "max_bid_per_cu_hour_wei must be 1 to"),
    ("max_bid_per_cu_hour_wei", 2**128, "max_bid_per_cu_hour_wei must be 1 to"),
    ("gas_level", 10**18 - 1, "gas_level must be 1000000000000000000 to"),
    ("gas_level", 2**128, "gas_level must be 1000000000000000000 to"),
    ("required_gflops", 401, "above its GFLOPS ceiling of 400"),
    ("validators", 2, "takes one instance"),
])
def test_a_term_out_of_the_pox_s_bound_is_refused_before_anything_is_sent(key, value, message):
    with pytest.raises(ValueError, match=message):
        claims_settings(dict(V2, max_gflops=400, **{key: value}))


def test_the_bounds_themselves_are_taken():
    settings = claims_settings(dict(V2, max_price_per_cu_hour_wei=2**128 - 1, max_bid_per_cu_hour_wei=2**128 - 1,
                                    gas_level=2**128 - 1, max_gflops=400, required_gflops=400))
    assert settings.bid_wei == settings.max_bid_wei == settings.gas_level == 2**128 - 1
    assert claims_settings(dict(V2, gas_level=10**18, required_gflops=60_000)).required_gflops == 60_000
    assert claims_settings(dict(V2, validators=0)).bid_wei == 10**18


def test_a_raise_past_the_bid_ceiling_is_reported_not_sent():
    quote = matching.Quote(b"\x00" * 32, 5, 0, 2**128, 0, 10**18, 0)
    decision = matching.decide_raise(quote, 0, 0, False, 1, 8, 0, 5, 2**128 - 1)
    assert decision.action == matching.REPORT and "above the bid ceiling" in decision.reason


# ------------------------------------------------------------- requests that take no claims

def _raising_chain(runner, **state):
    chain = FakeChain(runner, last_block=1008, **state)
    return chain


def _quote_of(case):
    e = case["expected"]
    return {"counted": e["counted"], "canClaimNow": e["canClaimNow"], "minBidWei": int(e["minBidWei"]),
            "baseNowWei": int(e["baseNowWei"]), "bidWei": int(e["bidWei"]), "addedEscrowWei": 10**17}


@pytest.mark.parametrize("name", ["quote-claims-off", "quote-cancelled-request"])
def test_a_request_that_takes_no_claims_is_never_raised(name):
    case = QUOTES[name]
    assert case["expected"]["takesClaims"] is False and case["expected"]["canClaimNow"] == 0
    runner = Runner()
    chain = _raising_chain(runner, quote=_quote_of(case))
    if name == "quote-claims-off":
        chain.claims_on_set = False
    else:
        chain.status = 2
    path = path_of(runner, chain, max_bid_per_cu_hour_wei=10**19)
    assert path.await_approval(301, 600) is None
    assert chain.sent == [] and runner.allowances == [] and chain.quote_minimums == []
    assert chain.block == 1001
    assert path.claims_off is (name == "quote-claims-off")


def test_the_same_quote_with_claims_taken_is_raised():
    case = QUOTES["quote-cancelled-request"]
    runner = Runner()
    chain = _raising_chain(runner, quote=_quote_of(case))
    path_of(runner, chain, max_bid_per_cu_hour_wei=10**19).await_approval(301, 600)
    assert any(s[0] == "increase_bid" for s in chain.sent)


def test_an_open_request_s_claimable_nodes_hold_the_raise():
    case = QUOTES["quote-open-request"]
    assert case["expected"]["takesClaims"] is True and case["expected"]["canClaimNow"] == 5
    runner = Runner()
    chain = _raising_chain(runner, quote=_quote_of(case))
    path_of(runner, chain, max_bid_per_cu_hour_wei=10**19).await_approval(301, 600)
    assert not any(s[0] == "increase_bid" for s in chain.sent)


def test_a_pinned_request_is_not_served_by_the_claims_wait():
    case = QUOTES["quote-pinned-request"]
    assert case["expected"]["takesClaims"] is False
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner._claims = SimpleNamespace(await_approval=lambda *args: pytest.fail("a pinned request waited for claims"))
    runner.node_address = N1
    runner.running = False
    assert runner.check_order_for_task() is False


def test_past_its_age_the_wait_ends_for_the_cancel():
    runner = Runner()
    chain = _raising_chain(runner)
    chain.created_at = NOW - PARAMS["maxRequestAgeSeconds"] - 1
    path = path_of(runner, chain, max_bid_per_cu_hour_wei=10**19)
    assert path.await_approval(301, 600) is None
    assert chain.sent == [] and chain.block == 1001 and not path.claims_off
    assert any("past maxRequestAgeSeconds" in n for n in runner.matching_notices)
    chain = _raising_chain(Runner(), claims=[(N1, 1002, True)])
    chain.created_at = NOW - PARAMS["maxRequestAgeSeconds"]
    assert path_of(chain.runner, chain).await_approval(301, 600) == 77


def test_takes_claims():
    assert matching.takes_claims(True, 0, 100, 50, 150)
    assert not matching.takes_claims(True, 0, 100, 50, 151)
    assert not matching.takes_claims(False, 0, 100, 50, 120)
    assert not matching.takes_claims(True, 1, 100, 50, 120) and not matching.takes_claims(True, 2, 100, 50, 120)


def test_a_request_whose_set_has_claims_off_is_served_without_claims():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.do_request = 301
    runner.running = True
    runner._claims = SimpleNamespace(await_approval=lambda *args: None, claims_off=True)
    waited = []
    runner.find_order = lambda do_request: waited.append(do_request) or True
    assert runner.check_order_for_task() is True
    assert runner._claims is None and waited == [301]
    runner._claims = SimpleNamespace(await_approval=lambda *args: None, claims_off=False)
    runner.cancel_unclaimed_request = lambda wait_seconds: waited.append("cancel") or False
    assert runner.check_order_for_task() is False and waited[-1] == "cancel"


# ------------------------------------------------------------- defaults (OD26) and rounding

def test_the_v2_defaults_are_0_0_and_1e18():
    settings = v2_settings({"max_price_per_cu_hour_wei": 1, "escrow_wei": 2})
    assert (settings.max_gflops, settings.required_gflops, settings.relays_per_hour, settings.gas_level,
            settings.epc_units) == (0, 0, 0, 10**18, 0)


def test_a_resource_of_0_takes_its_default():
    assert protocolContract.request_terms({"cpu": 0, "memory": None, "storage": 0, "duration": 3}) == {
        "cpu": 1, "memory": 1, "storage": 40, "bandwidth": 1, "duration": 3, "validators": 1, "taskPrice": 10}


@pytest.mark.parametrize("score,units", [(0.5, 5000), ("0.5", 5000), (0.00005, 1), (0.00004, 0), (0.12345, 1235),
                                         ("0.12345", 1235), (1.00005, 10001), (5, 50_000), ("4.99995", 50_000),
                                         (1e-7, 0), ("2.5e-1", 2500), (0.00015, 2)])
def test_the_score_is_rounded_half_up_on_its_decimal_text(score, units):
    assert matching.score_units(score) == units


@pytest.mark.parametrize("score", [5.00005, -0.00005, "", "0x1", "1_0", True, float("nan"), float("inf")])
def test_a_score_outside_0_to_5_or_not_a_decimal_is_refused(score):
    with pytest.raises(ValueError, match="minimum node score"):
        matching.score_units(score)


# ------------------------------------------------------------- receipts

def test_a_note_refund_or_note_ambiguous_of_status_0_is_not_reported_as_sent():
    runner = Runner()
    receipts = iter([{"status": 1, "logs": []}, {"status": 0, "logs": []}])
    runner.poll_transaction = lambda tx, max_attempts=10: next(receipts)
    chain = FakeChain(runner)
    path_of(runner, chain).expired(77)
    assert chain.sent == [("expire_order", 77), ("note_refund", 77)]
    assert not any("noteRefund recorded" in n for n in runner.matching_notices)
    assert any("noteRefund 0xnote_refund of order 77 did not succeed" in n for n in runner.matching_notices)
    runner = Runner()
    runner.poll_transaction = lambda tx, max_attempts=10: {"status": 0, "logs": []}
    chain = FakeChain(runner)
    chain.time = NOW + 7200
    runner.matching_pending = [{"kind": "note", "order": 77, "chain": chain, "after": NOW, "hints": [1, 2, 3]}]
    settle_pending(runner)
    assert chain.sent == [("note_ambiguous", 77, (1, 2, 3))] and runner.matching_pending == []
    assert not any("noteAmbiguous of order 77 sent" in n for n in runner.matching_notices)
    assert any("did not succeed" in n for n in runner.matching_notices)


def test_mined_reads_the_status():
    assert claims_module.mined({"status": 1}) and not claims_module.mined({"status": 0})
    assert not claims_module.mined(None)


# ------------------------------------------------------------- the stored result (OD11)

def _task_runner(monkeypatch, generation, prefixed):
    """test_session_summary_signer's AMOY runner holding a task whose result
    its challenge's wallet signed, on a PoX of `generation`; the stored
    result carries the transaction's hex with "0x" when `prefixed`, bare as
    the runner's earlier reading admits otherwise."""
    from test_session_summary_signer import (DO_REQUEST, DP_REQUEST, GENUINE_WALLET, NODE, ORDER, WALLET, _challenge_key,
                                             _envelope, _Order, _runner)
    monkeypatch.setattr(runner_module, "read_generation", lambda contract: generation)
    challenge = b"the task's challenge"
    runner = _runner(_Order([]), _challenge_key(challenge.decode()), _envelope(GENUINE_WALLET, {"n": 1, "by": "x"}))
    runner.order, runner.challenge_hash = [WALLET, NODE, DO_REQUEST, DP_REQUEST, 2], challenge
    runner.enclave_image_ipfs_hash, runner.resources = "QmImage", {"duration": 2}
    stored = runner.contract.get_result_from_order
    assert not stored(ORDER).startswith("v3:0x")
    runner.contract.get_result_from_order = lambda order_id: (
        stored(order_id).replace("v3:", "v3:0x", 1) if prefixed else stored(order_id))
    return runner, ORDER


@pytest.mark.parametrize("prefixed", [True, False])
def test_on_a_network_without_pox_matching_the_stored_result_is_read_as_before(monkeypatch, prefixed):
    runner, order = _task_runner(monkeypatch, PoxGeneration("1.2", ZERO), prefixed)
    assert runner.get_result_from_order(order) is not None


def test_on_a_network_with_pox_matching_only_a_stored_result_decoded_for_the_order_is_taken(monkeypatch):
    runner, order = _task_runner(monkeypatch, PoxGeneration("2.0", MATCHING), True)
    assert runner.get_result_from_order(order) is not None
    runner, order = _task_runner(monkeypatch, PoxGeneration("2.0", MATCHING), False)
    assert runner.get_result_from_order(order) is None
    assert "outside the grammar of spec/matching.md 17 (noTransaction)" in runner._fault


# ------------------------------------------------------------- the securelock's own session

def _session_registry(sessions_address, record_name, latest=b"\x09" * 32):
    return Deployed(sessions_address, {
        "sessionOfImage": b"\x01" * 32,
        "record": lambda id: (b"\x00" * 32, ZERO, record_name if id == b"\x01" * 32 else "sl-session", 1, "",
                              "QmCurrent", 1, 0, True),
        "latest": latest})


def _image_registry(registry, sessions, own_session):
    return Deployed(registry, {"imageRecords": (1, 3, True, 4, True, 45_000, b"\x01" * 32, b"\x02" * 32),
                               "defaultRelease": lambda index: (1, "QmTrustedzone") + (b"\x00" * 32,) * 6,
                               "sessionRegistry": sessions, "getImageSession": own_session})


@pytest.mark.parametrize("bound_name,own,kept", [("sl-session", "sl-session", True),
                                                 ("tz-session", "sl-session", False),
                                                 ("sl-session", REVERT, False)])
def test_the_session_counts_only_when_it_is_the_securelock_s_own(bound_name, own, kept):
    registry, sessions = "0x" + "03" * 20, "0x" + "04" * 20
    images = _image_registry(registry, sessions, own)
    if isinstance(own, BaseException):
        def refuse(cid):
            raise own
        images.functions.answers["getImageSession"] = refuse
    deployed = {registry: images, sessions: _session_registry(sessions, bound_name)}
    found = contracts_with({"imageRegistry": registry}, deployed=deployed).image_records(IMAGE)
    if kept:
        assert found["session"] == b"\x01" * 32 and found["latest"] == b"\x09" * 32
        assert found["current_image"] == "QmCurrent"
    else:
        assert found["session"] == b"\x00" * 32 and found["latest"] == b"\x00" * 32
        assert found["current_image"] is None
