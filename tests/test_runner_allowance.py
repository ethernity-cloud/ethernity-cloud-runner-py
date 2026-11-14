"""The allowance before a DO request: EthernityCloudRunner.escrow_needs_allowance
holds when the network's protocol address differs from its token address (the
PoX pulls the escrow with transferFrom, so the wallet approves it on the token
first) and not when the protocol is the token (the bloxberg mainnet PoX takes
the escrow from the caller's balance). The bloxberg testnet table names the
PoX 1.2 beside the legacy proxy, which stays the token. No chain: the
contracts, the registry and the session are stand-ins."""
from types import SimpleNamespace

import pytest

import ethernity_cloud_runner_py.runner as runner_module
import ethernity_cloud_runner_py.session as session_module
from ethernity_cloud_runner_py.enums import ECEvent, ECNetwork
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

BLOXBERG_TESTNET_POX_1_2 = "0x7E7C6eB435E3687CfDfe18C09C0340eb70567d7b"
BLOXBERG_TESTNET_TOKEN = "0x02882F03097fE8cD31afbdFbB5D72a498B41112c"
BLOXBERG_MAINNET_POX = "0x549A6E06BB2084100148D50F51CF77a3436C3Ae7"
TX = "0x" + "ab" * 32
WALLET = "0x" + "11" * 20
PRICE = 5


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


def test_the_bloxberg_mainnet_protocol_is_its_token():
    assert ECNetwork.BLOXBERG.MAINNET.PROTOCOL_ADDRESS == BLOXBERG_MAINNET_POX
    assert ECNetwork.BLOXBERG.MAINNET.TOKEN_ADDRESS == BLOXBERG_MAINNET_POX


def test_the_bloxberg_mainnet_is_the_one_entry_whose_protocol_is_its_token():
    same = [(network_name, type_name) for network_name, type_name, entry in _networks()
            if entry.PROTOCOL_ADDRESS.lower() == entry.TOKEN_ADDRESS.lower()]
    assert same == [("BLOXBERG", "MAINNET")]


@pytest.mark.parametrize("network_type", ["TESTNET", "TESTNET_UNSAFE"])
def test_a_bloxberg_testnet_client_approves_the_escrow(network_type):
    assert EthernityCloudRunner("BLOXBERG", network_type).escrow_needs_allowance() is True


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


def _stubbed_runner(monkeypatch, network_type, allowance):
    """A bloxberg `network_type` runner whose wallet holds a balance of 100
    and an allowance of `allowance` on the token, with the submission steps
    around the allowance check stubbed. Records the allowance reads as
    (owner, spender) in runner.allowance_reads and the approvals as their
    prices in runner.approvals."""
    runner = EthernityCloudRunner("BLOXBERG", network_type)
    runner.running = True
    runner.price = PRICE
    runner.signer = SimpleNamespace(address=WALLET)
    runner.allowance_reads = []
    runner.approvals = []

    def set_allowance(price):
        runner.approvals.append(price)
        return TX

    def allowance_of(owner, spender):
        runner.allowance_reads.append((owner, spender))
        return SimpleNamespace(call=lambda: allowance)

    runner.contract = SimpleNamespace(
        get_balance=lambda: 100,
        get_protocol_address=lambda: runner.network_config.PROTOCOL_ADDRESS,
        set_allowance=set_allowance)
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(allowance=allowance_of))
    runner.check_web3_connection = lambda: True
    runner.get_enclave_details = lambda: True
    runner.create_task = lambda code: True
    runner.poll_transaction = lambda tx_hash, max_attempts: {"status": 1}
    monkeypatch.setattr(runner_module, "ImageRegistryContract", lambda *args: SimpleNamespace())
    return runner


def _init_step(monkeypatch, network_type, allowance):
    """Runs the INIT step of a run attempt."""
    runner = _stubbed_runner(monkeypatch, network_type, allowance)
    runner.event_queue.put(ECEvent.INIT)
    runner._run_attempt("code", "", {"taskPrice": PRICE})
    assert runner.processed_events == ["INIT"]
    return runner


def _session_submission(monkeypatch, network_type, allowance):
    """Runs a session's submission up to the order's approval."""
    runner = _stubbed_runner(monkeypatch, network_type, allowance)
    runner._resolve_storage = lambda: None

    def check_order_for_task():
        runner.order_id = 7
        return True

    runner.check_order_for_task = check_order_for_task
    runner.approve_task = lambda: True
    monkeypatch.setattr(session_module, "EthernityCloudSession",
                        lambda runner, order_id: SimpleNamespace(order_id=order_id))
    session = runner.run_session({"taskPrice": PRICE}, "securelock", "v1", "code")
    assert session.order_id == 7
    return runner


def test_the_bloxberg_testnet_init_step_approves_a_short_allowance(monkeypatch):
    runner = _init_step(monkeypatch, "TESTNET", allowance=0)
    assert runner.allowance_reads == [(WALLET, BLOXBERG_TESTNET_POX_1_2)]
    assert runner.approvals == [PRICE]


def test_the_bloxberg_testnet_init_step_keeps_a_sufficient_allowance(monkeypatch):
    runner = _init_step(monkeypatch, "TESTNET", allowance=10 ** 30)
    assert runner.allowance_reads == [(WALLET, BLOXBERG_TESTNET_POX_1_2)]
    assert runner.approvals == []


def test_the_bloxberg_testnet_init_step_fails_on_a_refused_approval(monkeypatch):
    runner = _stubbed_runner(monkeypatch, "TESTNET", allowance=0)
    runner.poll_transaction = lambda tx_hash, max_attempts: {"status": 0}
    runner.event_queue.put(ECEvent.INIT)
    with pytest.raises(ValueError, match="Allowance approval failed"):
        runner._run_attempt("code", "", {"taskPrice": PRICE})


def test_the_bloxberg_mainnet_init_step_reads_no_allowance(monkeypatch):
    runner = _init_step(monkeypatch, "MAINNET", allowance=0)
    assert runner.allowance_reads == []
    assert runner.approvals == []


def test_a_bloxberg_testnet_session_approves_a_short_allowance(monkeypatch):
    runner = _session_submission(monkeypatch, "TESTNET", allowance=0)
    assert runner.allowance_reads == [(WALLET, BLOXBERG_TESTNET_POX_1_2)]
    assert runner.approvals == [PRICE]


def test_a_bloxberg_mainnet_session_reads_no_allowance(monkeypatch):
    runner = _session_submission(monkeypatch, "MAINNET", allowance=0)
    assert runner.allowance_reads == []
    assert runner.approvals == []
