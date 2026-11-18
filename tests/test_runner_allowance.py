"""The allowance step before a DO request, EthernityCloudRunner.check_allowance.
On every network whose protocol address differs from its token address
(escrow_needs_allowance) the PoX pulls the request's escrow with transferFrom,
so the wallet's allowance for the protocol on the token is read and, when it
is below the escrow (protocolContract.request_escrow: taskPrice * validators *
duration tokens), the protocol is approved for exactly the escrow and the
approval waited for; where the protocol is the token (the bloxberg mainnet PoX
takes the escrow from the caller's balance) nothing is read or approved. The
bloxberg testnet names the PoX 1.2 beside the legacy proxy, which stays the
token, and walks the step by the code and amounts Polygon Amoy does. No chain:
the contracts, the registry and the session are stand-ins."""
from types import SimpleNamespace

import pytest
from web3 import Web3

import ethernity_cloud_runner_py.runner as runner_module
import ethernity_cloud_runner_py.session as session_module
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECEvent, ECNetwork, ECStatus
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

BLOXBERG_TESTNET_POX_1_2 = "0x830c781F0352050343211B6BFA83600B3e77647C"
BLOXBERG_TESTNET_TOKEN = "0x02882F03097fE8cD31afbdFbB5D72a498B41112c"
BLOXBERG_MAINNET_POX = "0x549A6E06BB2084100148D50F51CF77a3436C3Ae7"
AMOY_POX_1_2 = "0xd1182deA61CDa785C320cdBE5888EaC4178cAAF2"
AMOY_TOKEN = "0x9927809B61122B2af3f3b3A3303875e0687b8eE3"
TX = "0x" + "ab" * 32
WALLET = "0x" + "11" * 20
# The one stand-in protocol every network's runner is given, so that their
# walks through the step can be compared call for call.
PROTOCOL = "0x" + "22" * 20
PRICE = 5
RESOURCES = {"taskPrice": PRICE, "cpu": 1, "memory": 1, "storage": 40,
             "bandwidth": 1, "duration": 1, "validators": 1}
# Three instances over two hours: the PoX pulls 5 * 3 * 2 tokens.
TERMED = {"taskPrice": PRICE, "validators": 3, "duration": 2}
TERMED_ESCROW = 30
# The networks whose PoX is apart from the token and served by the runner's
# default storage: the bloxberg testnet and Polygon Amoy, each with its
# -unsafe twin.
SEPARATE_PROTOCOL_NETWORKS = [("BLOXBERG", "TESTNET"), ("BLOXBERG", "TESTNET_UNSAFE"),
                              ("POLYGON", "AMOY"), ("POLYGON", "AMOY_UNSAFE")]


def _networks():
    """(network name, type name, table entry) for every entry of ECNetwork."""
    for network_name, network in vars(ECNetwork).items():
        if network_name.startswith("_"):
            continue
        for type_name, entry in vars(network).items():
            if not type_name.startswith("_"):
                yield network_name, type_name, entry


def test_the_bloxberg_testnet_table_names_the_pox_1_2_beside_the_legacy_token():
    assert ECNetwork.BLOXBERG.TESTNET.PROTOCOL_ADDRESS == BLOXBERG_TESTNET_POX_1_2
    assert ECNetwork.BLOXBERG.TESTNET.TOKEN_ADDRESS == BLOXBERG_TESTNET_TOKEN
    assert ECNetwork.BLOXBERG.TESTNET_UNSAFE.PROTOCOL_ADDRESS == BLOXBERG_TESTNET_POX_1_2
    assert ECNetwork.BLOXBERG.TESTNET_UNSAFE.TOKEN_ADDRESS == BLOXBERG_TESTNET_TOKEN


def test_the_amoy_table_names_the_pox_1_2_beside_the_tecld_token():
    assert ECNetwork.POLYGON.AMOY.PROTOCOL_ADDRESS == AMOY_POX_1_2
    assert ECNetwork.POLYGON.AMOY.TOKEN_ADDRESS == AMOY_TOKEN
    assert ECNetwork.POLYGON.AMOY_UNSAFE.PROTOCOL_ADDRESS == AMOY_POX_1_2
    assert ECNetwork.POLYGON.AMOY_UNSAFE.TOKEN_ADDRESS == AMOY_TOKEN


def test_the_bloxberg_mainnet_protocol_is_its_token():
    assert ECNetwork.BLOXBERG.MAINNET.PROTOCOL_ADDRESS == BLOXBERG_MAINNET_POX
    assert ECNetwork.BLOXBERG.MAINNET.TOKEN_ADDRESS == BLOXBERG_MAINNET_POX


def test_the_bloxberg_mainnet_is_the_one_entry_whose_protocol_is_its_token():
    same = [(network_name, type_name) for network_name, type_name, entry in _networks()
            if entry.PROTOCOL_ADDRESS.lower() == entry.TOKEN_ADDRESS.lower()]
    assert same == [("BLOXBERG", "MAINNET")]


@pytest.mark.parametrize("network_name, network_type", SEPARATE_PROTOCOL_NETWORKS)
def test_a_client_of_a_pox_apart_from_the_token_approves_the_escrow(network_name, network_type):
    assert EthernityCloudRunner(network_name, network_type).escrow_needs_allowance() is True


def test_a_bloxberg_mainnet_client_approves_nothing():
    assert EthernityCloudRunner("BLOXBERG", "MAINNET").escrow_needs_allowance() is False


def test_the_rule_is_the_tables_addresses_for_every_network():
    for network_name, type_name, entry in _networks():
        runner = EthernityCloudRunner(network_name, type_name)
        expected = entry.PROTOCOL_ADDRESS.lower() != entry.TOKEN_ADDRESS.lower()
        assert runner.escrow_needs_allowance() is expected, f"{network_name} {type_name}"


def test_the_rule_compares_the_addresses_without_regard_to_case():
    runner = EthernityCloudRunner("BLOXBERG", "MAINNET")
    runner.network_config = SimpleNamespace(PROTOCOL_ADDRESS=BLOXBERG_MAINNET_POX.lower(),
                                            TOKEN_ADDRESS=BLOXBERG_MAINNET_POX)
    assert runner.escrow_needs_allowance() is False


def test_the_request_escrow_is_the_price_of_every_instance_over_the_duration():
    assert protocolContract.request_escrow(TERMED) == TERMED_ESCROW
    assert protocolContract.request_escrow(RESOURCES) == PRICE


def test_a_request_takes_the_defaults_for_the_terms_it_leaves_out():
    assert protocolContract.request_terms({}) == protocolContract.REQUEST_DEFAULTS
    assert protocolContract.request_escrow({}) == 10
    assert protocolContract.request_terms(TERMED)["cpu"] == 1
    assert protocolContract.request_terms(TERMED)["validators"] == 3


def _stubbed_runner(monkeypatch, network_name, network_type, allowance,
                    resources=RESOURCES, balance=100, protocol=None):
    """A `network_name` `network_type` runner whose wallet holds `balance`
    tokens and an allowance of `allowance` wei for the protocol on the token,
    with the submission steps around the balance and allowance checks stubbed.
    The protocol is `protocol` when given, else the network's. runner.calls
    records, in order, the faucet draws ("faucet",), the allowance reads
    ("allowance", owner, spender), the approvals ("approve", tokens) and the
    waits for their receipt ("wait", tx)."""
    runner = EthernityCloudRunner(network_name, network_type)
    runner.running = True
    runner.resources = resources
    runner.signer = SimpleNamespace(address=WALLET)
    runner.calls = []

    def faucet():
        runner.calls.append(("faucet",))

    def set_allowance(tokens):
        runner.calls.append(("approve", tokens))
        return TX

    def allowance_of(owner, spender):
        runner.calls.append(("allowance", owner, spender))
        return SimpleNamespace(call=lambda: allowance)

    def poll_transaction(tx_hash, max_attempts):
        runner.calls.append(("wait", tx_hash))
        return {"status": 1}

    runner.contract = SimpleNamespace(
        get_balance=lambda: balance,
        get_protocol_address=lambda: protocol or runner.network_config.PROTOCOL_ADDRESS,
        set_allowance=set_allowance,
        faucet=faucet)
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(allowance=allowance_of))
    runner.check_web3_connection = lambda: True
    runner.get_enclave_details = lambda: True
    runner.create_task = lambda code: True
    runner.poll_transaction = poll_transaction
    monkeypatch.setattr(runner_module, "ImageRegistryContract", lambda *args: SimpleNamespace())
    return runner


def _init_step(monkeypatch, network_name, network_type, allowance, **stub):
    """Runs the INIT step of a run attempt."""
    runner = _stubbed_runner(monkeypatch, network_name, network_type, allowance, **stub)
    runner.event_queue.put(ECEvent.INIT)
    runner._run_attempt("code", "", runner.resources)
    assert runner.processed_events == ["INIT"]
    return runner


def _session_submission(monkeypatch, network_name, network_type, allowance, **stub):
    """Runs a session's submission up to the order's approval."""
    runner = _stubbed_runner(monkeypatch, network_name, network_type, allowance, **stub)
    runner._resolve_storage = lambda: None

    def check_order_for_task():
        runner.order_id = 7
        return True

    runner.check_order_for_task = check_order_for_task
    runner.approve_task = lambda: True
    monkeypatch.setattr(session_module, "EthernityCloudSession",
                        lambda runner, order_id: SimpleNamespace(order_id=order_id))
    session = runner.run_session(runner.resources, "securelock", "v1", "code")
    assert session.order_id == 7
    return runner


SUBMISSIONS = pytest.mark.parametrize("submission", [_init_step, _session_submission],
                                      ids=["init", "session"])


@SUBMISSIONS
def test_the_bloxberg_testnet_and_amoy_walk_the_same_allowance_step(monkeypatch, submission):
    walks = {}
    for network_name, network_type in SEPARATE_PROTOCOL_NETWORKS:
        runner = submission(monkeypatch, network_name, network_type, allowance=0,
                            resources=TERMED, protocol=PROTOCOL)
        walks[(network_name, network_type)] = runner.calls
    assert walks[("BLOXBERG", "TESTNET")] == [
        ("allowance", WALLET, PROTOCOL), ("approve", TERMED_ESCROW), ("wait", TX)]
    assert walks[("POLYGON", "AMOY")] == walks[("BLOXBERG", "TESTNET")]
    assert all(calls == walks[("BLOXBERG", "TESTNET")] for calls in walks.values())


@SUBMISSIONS
def test_the_bloxberg_mainnet_reads_no_allowance(monkeypatch, submission):
    runner = submission(monkeypatch, "BLOXBERG", "MAINNET", allowance=0, resources=TERMED)
    assert runner.calls == []


def test_the_bloxberg_testnet_approves_its_pox_1_2_on_the_token(monkeypatch):
    runner = _init_step(monkeypatch, "BLOXBERG", "TESTNET", allowance=0)
    assert runner.calls == [("allowance", WALLET, BLOXBERG_TESTNET_POX_1_2), ("approve", PRICE), ("wait", TX)]


def test_amoy_approves_its_pox_1_2_on_the_token(monkeypatch):
    runner = _init_step(monkeypatch, "POLYGON", "AMOY", allowance=0)
    assert runner.calls == [("allowance", WALLET, AMOY_POX_1_2), ("approve", PRICE), ("wait", TX)]


@pytest.mark.parametrize("network_name, network_type", SEPARATE_PROTOCOL_NETWORKS)
def test_an_allowance_at_the_escrow_is_left_as_it_is(monkeypatch, network_name, network_type):
    runner = _init_step(monkeypatch, network_name, network_type,
                        allowance=Web3.to_wei(TERMED_ESCROW, "ether"), resources=TERMED, protocol=PROTOCOL)
    assert runner.calls == [("allowance", WALLET, PROTOCOL)]


@pytest.mark.parametrize("network_name, network_type", SEPARATE_PROTOCOL_NETWORKS)
def test_an_allowance_a_wei_below_the_escrow_is_raised_to_it(monkeypatch, network_name, network_type):
    runner = _init_step(monkeypatch, network_name, network_type,
                        allowance=Web3.to_wei(TERMED_ESCROW, "ether") - 1, resources=TERMED, protocol=PROTOCOL)
    assert runner.calls == [("allowance", WALLET, PROTOCOL), ("approve", TERMED_ESCROW), ("wait", TX)]


def test_the_allowance_is_compared_with_the_escrow_in_wei(monkeypatch):
    # An allowance of as many wei as the escrow has tokens is below it.
    runner = _init_step(monkeypatch, "BLOXBERG", "TESTNET", allowance=TERMED_ESCROW, resources=TERMED)
    assert [call[0] for call in runner.calls] == ["allowance", "approve", "wait"]


def test_a_refused_approval_fails_the_submission(monkeypatch):
    runner = _stubbed_runner(monkeypatch, "BLOXBERG", "TESTNET", allowance=0)
    runner.poll_transaction = lambda tx_hash, max_attempts: {"status": 0}
    runner.event_queue.put(ECEvent.INIT)
    with pytest.raises(ValueError, match="Allowance approval failed"):
        runner._run_attempt("code", "", RESOURCES)


def test_both_submissions_run_the_one_allowance_step(monkeypatch):
    runs = []
    monkeypatch.setattr(EthernityCloudRunner, "check_allowance",
                        lambda self: runs.append((self.network_name, self.network_type)))
    _init_step(monkeypatch, "BLOXBERG", "TESTNET", allowance=0)
    _session_submission(monkeypatch, "POLYGON", "AMOY", allowance=0)
    assert runs == [("BLOXBERG", "TESTNET"), ("POLYGON", "AMOY")]


def test_a_resubmission_approves_the_escrow_again(monkeypatch):
    # addDORequest pulled the first request's escrow, the whole allowance.
    runner = _stubbed_runner(monkeypatch, "BLOXBERG", "TESTNET", allowance=0, resources=TERMED)
    runner.max_retries = 1
    runner.retry_delay = 0
    runner.check_order_for_task = lambda: True
    runner.approve_task = lambda: True

    def process_task():
        runner._fault = "the node withheld the result"
        return False

    runner.process_task = process_task
    runner._populate_event_queue()
    runner._process_events("code", "", TERMED)
    assert runner.status == ECStatus.ERROR
    walk = [("allowance", WALLET, BLOXBERG_TESTNET_POX_1_2), ("approve", TERMED_ESCROW), ("wait", TX)]
    assert runner.calls == walk + walk


def test_a_testnet_wallet_below_the_escrow_draws_the_faucet_first(monkeypatch):
    runner = _init_step(monkeypatch, "BLOXBERG", "TESTNET", allowance=0, resources=TERMED, balance=TERMED_ESCROW - 1)
    assert runner.calls[0] == ("faucet",)
    assert runner.calls[1:] == [("allowance", WALLET, BLOXBERG_TESTNET_POX_1_2), ("approve", TERMED_ESCROW), ("wait", TX)]


def test_a_mainnet_wallet_below_the_escrow_fails_the_submission(monkeypatch):
    runner = _stubbed_runner(monkeypatch, "BLOXBERG", "MAINNET", allowance=0, resources=TERMED, balance=TERMED_ESCROW - 1)
    runner.event_queue.put(ECEvent.INIT)
    with pytest.raises(ValueError, match="Insufficient wallet balance. Required: 30, Available: 29"):
        runner._run_attempt("code", "", TERMED)
    assert runner.calls == []
