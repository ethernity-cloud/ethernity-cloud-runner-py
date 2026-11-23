"""EthernityCloudRunner chooses per request, before its add, between the
claims path and the path it has served requests by before (MATCHING-DESIGN.md
section 8 item 4 and section 13, roll-out step 3): a network whose entry
names no PoxMatching, every PoX 1.0 network among them, reads nothing of
matching; on one that names it, claimsOn() decides, and with claims off the
request is added and approved as before. A request pinned to a banned node is
refused on such a network whatever claimsOn() answers (D33). No chain: the
contracts are stand-ins."""
from types import SimpleNamespace

import pytest

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.claims import ClaimsPath
from ethernity_cloud_runner_py.enums import ECNetwork
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

RESOURCES = {"taskPrice": 1, "cpu": 1, "memory": 1, "storage": 1, "bandwidth": 1, "duration": 1, "validators": 1}
V2 = dict(RESOURCES, max_price_per_cu_hour_wei=10**18, escrow_wei=3 * 10**18, max_gflops=400, required_gflops=250)
NODE = "0x" + "12" * 20
TX = "0x" + "ab" * 32
NOW = 1795008240


def entries():
    for network_name, network in vars(ECNetwork).items():
        if network_name.startswith("_"):
            continue
        for type_name, entry in vars(network).items():
            if not type_name.startswith("_") and isinstance(entry, type):
                yield network_name, type_name, entry


@pytest.mark.parametrize("network_name,type_name", [(n, t) for n, t, _ in entries()])
def test_a_network_without_pox_matching_reads_nothing_of_it(network_name, type_name, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("MatchingContracts built for a network whose entry names no PoxMatching")
    monkeypatch.setattr(runner_module, "MatchingContracts", refuse)
    runner = EthernityCloudRunner(network_name, type_name)
    assert runner._claims_path(V2, NODE) is None


@pytest.mark.parametrize("network_name,type_name", [("BLOXBERG", "MAINNET"), ("BLOXBERG", "TESTNET_POX10"),
                                                    ("POLYGON", "MAINNET"), ("POLYGON", "AMOY_POX10")])
def test_the_pox_1_0_networks_name_no_pox_matching(network_name, type_name):
    entry = getattr(getattr(ECNetwork, network_name), type_name)
    assert getattr(entry, "MATCHING_ADDRESS", None) is None
    assert getattr(entry, "MATCH_READER_ADDRESS", None) is None


class Chain:
    def __init__(self, claims_on, banned_until=0):
        self.on = claims_on
        self.banned_until = banned_until
        self.reads = []

    def claims_on(self):
        self.reads.append("claimsOn")
        return self.on

    def node_standing(self, node):
        self.reads.append(("nodeStanding", node))
        return (0, 0, self.banned_until)

    def chain_time(self):
        return NOW


@pytest.fixture
def matching_network(monkeypatch):
    """BLOXBERG TESTNET's entry naming a PoxMatching and its reader, and the
    MatchingContracts the runner builds for it."""
    monkeypatch.setattr(ECNetwork.BLOXBERG.TESTNET, "MATCHING_ADDRESS", "0x" + "01" * 20, raising=False)
    monkeypatch.setattr(ECNetwork.BLOXBERG.TESTNET, "MATCH_READER_ADDRESS", "0x" + "02" * 20, raising=False)
    built = {}

    def build(claims_on, banned_until=0):
        chain = Chain(claims_on, banned_until)

        def contracts(contract, matching_address, reader_address, page_entries):
            built["args"] = (matching_address, reader_address, page_entries)
            return chain
        monkeypatch.setattr(runner_module, "MatchingContracts", contracts)
        return chain
    return build, built


def test_claims_off_serves_the_request_as_before(matching_network):
    build, built = matching_network
    chain = build(False)
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    assert runner._claims_path(V2, "") is None
    assert chain.reads == ["claimsOn"]
    assert built["args"] == ("0x" + "01" * 20, "0x" + "02" * 20, None)


def test_claims_on_serves_the_request_by_claims(matching_network):
    build, _ = matching_network
    build(True)
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    path = runner._claims_path(V2, "")
    assert isinstance(path, ClaimsPath)
    assert path.settings.bid_wei == 10**18 and path.settings.escrow_wei == 3 * 10**18


def test_claims_on_without_v2_terms_is_refused(matching_network):
    build, _ = matching_network
    build(True)
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    with pytest.raises(ValueError, match="V2 terms"):
        runner._claims_path(RESOURCES, "")


@pytest.mark.parametrize("claims_on", [False, True])
def test_a_request_pinned_to_a_banned_node_is_refused(matching_network, claims_on):
    build, _ = matching_network
    chain = build(claims_on, banned_until=NOW + 60)
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    with pytest.raises(ValueError, match="banned until"):
        runner._claims_path(V2, NODE)
    assert chain.reads == [("nodeStanding", NODE)]


def test_a_request_pinned_to_a_node_that_is_not_banned_goes_on(matching_network):
    build, _ = matching_network
    chain = build(False, banned_until=NOW)
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    assert runner._claims_path(V2, NODE) is None
    assert chain.reads == [("nodeStanding", NODE), "claimsOn"]


def _runner_with_request_event(claims):
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.resources = V2
    runner.running = True
    sent = []
    eth = SimpleNamespace(get_transaction_receipt=lambda tx_hash: {"status": 1})
    runner.contract = SimpleNamespace(add_do_request=lambda *args: sent.append(("legacy",) + args) or TX,
                                      get_provider=lambda: SimpleNamespace(eth=eth))
    log = SimpleNamespace(args=SimpleNamespace(_rowNumber=12))
    event = SimpleNamespace(process_receipt=lambda receipt, errors: [log])
    runner.protocol_contract = SimpleNamespace(events=SimpleNamespace(_addDORequestEV=lambda: event))
    if claims:
        runner._claims = SimpleNamespace(add_request=lambda metadata: sent.append(("v2", metadata)) or TX)
    return runner, sent


def test_the_claims_path_adds_its_request_with_v2_terms():
    runner, sent = _runner_with_request_event(True)
    assert runner.create_do_request("image", "code", "input", "") is True
    assert sent == [("v2", ["image", "code", "input", ""])]
    assert runner.do_request == 12


def test_the_path_as_before_adds_the_legacy_request():
    runner, sent = _runner_with_request_event(False)
    assert runner.create_do_request("image", "code", "input", "") is True
    assert sent == [("legacy", "image", "code", "input", "", V2)]


def test_the_claims_path_has_no_approval_of_its_own():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner._claims = SimpleNamespace()
    runner.running = True
    runner.approve_order = lambda: pytest.fail("the claims path sent _approveOrder")
    assert runner.approve_task() is True


def test_a_failed_end_carries_its_report_in_the_error():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.result = {"success": False, "result_task_code": "UNKNOWN_62", "result_task_code_int": 62,
                     "end_report": "The order failed with no result, task code 62 (SECURELOCK_SILENT)."}
    runner._finish("done")
    assert runner.last_error.endswith("task code 62 (SECURELOCK_SILENT).")
    runner.result = {"success": False, "result_task_code": "SYSTEM_ERROR", "result_task_code_int": 1}
    runner._finish("done")
    assert runner.last_error == ("The task failed in the enclave with SYSTEM_ERROR (1); the result holds its "
                                 "error report.")
