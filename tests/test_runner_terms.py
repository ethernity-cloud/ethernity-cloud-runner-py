"""spec/runner-terms.json (SF21; the copy in tests/spec/) replayed through
the runner's own request path: each case's settings are a run's resources,
the PoX answers the case's VERSION() and its pricing the case's matching()
(MATCHING with claims on, the zero address with claims off), the pricing's
bounds are the file's (gflopsMax 6,400, maxOrderHours 168) and the image
registry records the case's imageEpcUnits; the runner chooses the path,
checks the balance and the allowance and adds the request, as
EthernityCloudRunner._run_attempt does, with metadata of the case's sizes.
A case either names the add (its selector, the form of maxGflops and the
arguments, recorded from the addDORequestV2 send_v2_add builds), its minimum
EPC, the order of the sends, whether the claims path is taken, whether a
score test (a quote with a minimum score above 0) precedes the add and the
score units of the setting; or names a refusal, raised as a ValueError whose
message holds the case's message before anything is sent. A metadata bound
is tested after the approval (D206), so a metadata refusal follows the
approval and no add is sent. runner-terms-reads.json, which both runners
hold byte for byte, names the quote and the escrow each adding case reads
before its add (none off the claims path)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from eth_utils import keccak

from ethernity_cloud_runner_py import matching
from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.claims import ClaimsPath
from ethernity_cloud_runner_py.contract.operation import matchingContract
from ethernity_cloud_runner_py.contract.operation.matchingContract import PoxGeneration
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from spec_copies import load
from test_matching_claims import IMAGE, TEMPLATE, Images

TERMS = load("runner-terms.json")
READS = json.loads((Path(__file__).resolve().parent / "runner-terms-reads.json").read_text(encoding="utf-8"))
PROTOCOL = "0x" + "bb" * 20
PRICING = "0x" + "0c" * 20
MATCHING = "0x" + "01" * 20
ZERO = "0x" + "00" * 20
WALLET = "0x" + "aa" * 20
APPROVAL = "token.approve(pox, escrowWei)"
ADD = "addDORequestV2"
BOUNDS = matching.TermBounds(TERMS["rules"]["bounds"]["gflopsMax"], TERMS["rules"]["bounds"]["maxOrderHours"])
METADATA_REFUSALS = {"metadata1 too long", "metadata too long"}


class Sender:
    """EthernityCloudRunner._sender() as the request path calls it: the
    approval, and the addDORequestV2 built on the ABI the PoX's form names,
    called and sent; each send kept in order in `sends`."""

    def __init__(self):
        self.sends = []
        self.add = None
        self.protocol_address = PROTOCOL
        self.signer = SimpleNamespace(address=WALLET)
        self.provider = SimpleNamespace(eth=SimpleNamespace(contract=self._contract))

    def _contract(self, address, abi):
        def add(*args):
            self.add = (abi, args)
            return SimpleNamespace(call=lambda params: None)
        return SimpleNamespace(functions=SimpleNamespace(addDORequestV2=add))

    def set_allowance_wei(self, wei):
        self.sends.append(APPROVAL)
        return "0xapprove"

    def _build_sign_send(self, fn, gas):
        self.sends.append(ADD)
        return "0xadd"


class TermsChain(Images):
    """The network's MatchingContracts: claimsOn() as the case states, the
    image's recorded EPC need, the reader bound, and the add made through
    send_v2_add on the runner's sender."""

    def __init__(self, runner, sender, version, claims_on, image_epc):
        super().__init__(runner)
        self.sender, self.version = sender, version
        self.claims_on_answer = claims_on
        self.epc_need = image_epc

    def claims_on(self):
        return self.claims_on_answer

    def bind_reader(self):
        return "0x" + "02" * 20

    def add_do_request_v2(self, resources, bid_wei, max_gflops, relays_per_hour, gas_level, metadata):
        return matchingContract.send_v2_add(self.sender, self.version, resources, bid_wei, max_gflops,
                                            relays_per_hour, gas_level, metadata)


def resources_of(settings):
    """A run's resources for a case's settings (runner-terms.json `settings`)."""
    resources = {"cpu": settings["cpu"], "memory": settings["mem"], "storage": settings["storageGB"],
                 "bandwidth": settings["bw"], "duration": settings["hours"], "validators": settings["instances"],
                 "max_price_per_cu_hour_wei": int(settings["bid"]), "escrow_wei": 10**40}
    for key, name in (("ceilGflops", "max_gflops"), ("needGflops", "required_gflops"), ("clientEpcMiB", "epc_mib"),
                      ("relaysPerHour", "relays_per_hour")):
        if key in settings:
            resources[name] = settings[key]
    if "gasLevel" in settings:
        resources["gas_level"] = int(settings["gasLevel"])
    if "minScore" in settings:
        resources["min_node_score"] = settings["minScore"]
    return resources


def replay(case, monkeypatch):
    """The runner's request path for `case`: (runner, sender, chain, refusal)."""
    s = case["settings"]
    sender = Sender()
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.resources = resources_of(s)
    runner._sender = lambda: sender
    runner.signer = SimpleNamespace(address=WALLET)
    runner.contract = SimpleNamespace(get_protocol_address=lambda: PROTOCOL, get_balance=lambda: 10**30)
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(
        allowance=lambda wallet, protocol: SimpleNamespace(call=lambda: 0)))
    runner.poll_transaction = lambda tx, max_attempts=10: {"status": 1, "logs": []} if tx == "0xapprove" else None
    runner.enclave_image_ipfs_hash = IMAGE
    runner.trustedZoneImage = TEMPLATE
    generation = PoxGeneration(s["version"], MATCHING if s["matching"] == "set" else ZERO, PRICING)
    monkeypatch.setattr(runner_module, "read_generation", lambda contract: generation)
    monkeypatch.setattr(runner_module, "read_term_bounds", lambda contract, pricing: BOUNDS)
    chains = []

    def contracts(contract, address, page_entries, version):
        chains.append(TermsChain(runner, sender, version, s["claims"], s.get("imageEpcUnits", 0)))
        return chains[-1]

    monkeypatch.setattr(runner_module, "MatchingContracts", contracts)
    metadata = ("i" * s["metadata1Bytes"], "c" * s["metadataBytes"], "n" * s["metadataBytes"], "")
    try:
        runner._choose_path(runner.resources, "")
        runner._check_balance()
        runner.check_allowance()
        runner.create_do_request(*metadata)
    except ValueError as e:
        return runner, sender, chains[0] if chains else None, e
    return runner, sender, chains[0] if chains else None, None


def selector_of(abi):
    entry = next(e for e in abi if e.get("name") == ADD)
    return "0x" + keccak(text=f"{ADD}({','.join(i['type'] for i in entry['inputs'])})")[:4].hex(), entry


@pytest.mark.parametrize("case", TERMS["cases"], ids=[c["name"] for c in TERMS["cases"]])
def test_the_runner_terms_case(case, monkeypatch):
    runner, sender, chain, refusal = replay(case, monkeypatch)
    expected = case["expected"]
    if "refused" in expected:
        assert refusal is not None, "the request was not refused"
        assert expected["refused"]["message"] in str(refusal)
        assert sender.add is None
        late = expected["refused"]["message"] in METADATA_REFUSALS
        assert sender.sends == ([APPROVAL] if late else [])
        return
    assert refusal is None, refusal
    add = expected["add"]
    selector, entry = selector_of(sender.add[0])
    args = dict(zip([i["name"] for i in entry["inputs"]], sender.add[1]))
    assert selector == add["selector"]
    assert f"maxGflops {next(i['type'] for i in entry['inputs'] if i['name'] == 'maxGflops')}" == add["form"]
    assert {name: str(args[name]) if isinstance(value, str) else args[name]
            for name, value in add["args"].items()} == add["args"]
    assert args["maxGflops"] >> 32 == expected["epcUnits"]
    assert sender.sends == expected["sends"] == [APPROVAL, ADD]
    path = runner._claims or runner._termed
    assert isinstance(runner._claims, ClaimsPath) is expected["claimsPath"]
    assert path.settings.min_score == expected["minScoreUnits"]
    quotes = chain.quotes_for if chain is not None else []
    assert any(minimum > 0 for _terms, _template, minimum in quotes) is expected["scoreTestBeforeAdd"]
    reads = READS["cases"][case["name"]]
    if reads["quote"] is None:
        assert quotes == [] and (chain is None or chain.escrow_reads == [])
        return
    quote = dict(reads["quote"])
    template, minimum = quote.pop("template"), quote.pop("minScore")
    assert quotes == [(quote, template, minimum)]
    escrow = reads["escrow"]
    assert chain.escrow_reads == [(escrow["hours"], int(escrow["bidWei"]), int(escrow["maxGflops"]),
                                   escrow["relaysPerHour"], int(escrow["gasLevel"]), escrow["metadata1"])]


def test_every_adding_case_has_its_reads():
    adding = {c["name"] for c in TERMS["cases"] if "add" in c["expected"]}
    assert set(READS["cases"]) == adding
    assert READS["image"] == IMAGE and READS["template"] == TEMPLATE


def test_the_pricing_bounds_are_read_on_a_2_0_pox_only(monkeypatch):
    case = next(c for c in TERMS["cases"] if c["name"] == "defaults-claims-off")
    reads = []
    monkeypatch.setattr(runner_module, "read_term_bounds", lambda contract, pricing: reads.append(pricing) or BOUNDS)
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner._sender = lambda: Sender()
    for version, read in (("2.0", [PRICING]), ("1.2", [])):
        reads.clear()
        monkeypatch.setattr(runner_module, "read_generation", lambda contract: PoxGeneration(version, ZERO, PRICING))
        runner._choose_path(resources_of(case["settings"]), "")
        assert reads == read and runner._termed is not None
