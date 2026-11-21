"""EthernityCloudRunner.set_private_key gives a runner another wallet whole.
On a connected runner the protocol contract is built again for the runner's
network with the new signer, as connect() builds it, so every transaction of
a later run is signed by the new wallet and every read is made for it; the
image registry contract built with the wallet left, its order and that
order's node are dropped. A call that raises changes nothing: a key of
another form or one eth_account does not take, and a run or a session in
progress (RuntimeError). No log line, exception text or repr holds a key.
The two wallets are of keys generated when the module is loaded; no case
compares a key inside an assert, so a failure prints none. No chain: the
contracts, the provider that keeps every read, every transaction and the
wallet each names or is signed by, and the steps of a run after its request
are test_set_network.py's."""
import logging
import threading
from types import SimpleNamespace

import pytest
from eth_account import Account

import ethernity_cloud_runner_py.session as session_module
from ethernity_cloud_runner_py.enums import ECStatus

from test_set_network import (  # noqa: F401 (chain is the fixture the cases ask for)
    AMOY, AMOY_POX10, MAINNET, ORDER, RESOURCES, SECURELOCK, TESTNET, TESTNET_POX10, TX,
    _entry, _expected, _run, _runner, chain,
)


def _generated_key():
    """A key of this load of the module, 64 hex digits prefixed with 0x."""
    return "0x" + bytes(Account.create().key).hex()


KEY_A, KEY_B = _generated_key(), _generated_key()
A, B = Account.from_key(KEY_A).address, Account.from_key(KEY_B).address
NETWORKS = [AMOY, AMOY_POX10, TESTNET, TESTNET_POX10, MAINNET]
EVERY_NETWORK = pytest.mark.parametrize("network", NETWORKS, ids=[f"{name} {kind}" for name, kind in NETWORKS])
IN_PROGRESS = ("A run or a session of this runner is in progress on POLYGON AMOY: set_private_key() is refused "
               "until the run has ended or, after a session, the runner is closed with close(). Use another "
               "EthernityCloudRunner for another wallet.")
# Strings of the form of a key that are no key: two that the form check refuses and two eth_account refuses.
NOT_0X = "11" * 33
TOO_SHORT = "0x" + "11" * 31
NOT_HEX = "0x" + "zz" * 32
ABOVE_THE_CURVE_ORDER = "0x" + "ff" * 32


def _wallets(chain):
    """The wallets the requests of the chain named or were signed by."""
    return {wallet for _, wallet in chain.wallets}


def _is_wallet_of(runner, key):
    """Whether the runner's key is `key`, compared outside an assert."""
    return runner.private_key == key


def _held(runner):
    """What names the runner's wallet and its network, without the key: the signer, the contract objects,
    the image registry contract, the order and the network's names and entry."""
    return (runner.signer, runner.contract, runner.protocol_contract, runner.token_contract,
            runner.image_registry_contract, runner.order_id, runner.node_address,
            runner.network_name, runner.network_type, runner.network_config, runner.ipfs_client)


# ---- a run after a change of the wallet ----

@EVERY_NETWORK
def test_a_run_after_set_private_key_is_signed_by_and_read_for_the_new_wallet(chain, network):
    runner = _runner(network, key=KEY_A)
    _run(runner)
    assert chain.log == _expected(network, A)
    assert _wallets(chain) == {A}
    del chain.log[:], chain.wallets[:]
    runner.set_private_key(KEY_B)
    _run(runner)
    # The balance and allowance reads name B, and the approval, the request and the order's approval are B's.
    assert chain.log == _expected(network, B)
    assert _wallets(chain) == {B}
    assert [kind for kind, _ in chain.wallets if kind == "signed"] == ["signed"] * (
        3 if _entry(network).PROTOCOL_ADDRESS != _entry(network).TOKEN_ADDRESS else 2)


@EVERY_NETWORK
def test_a_first_run_after_set_private_key_names_the_wallet_left_nowhere(chain, network):
    runner = _runner(network, key=KEY_A)
    runner.set_private_key(KEY_B)
    assert chain.log == [] and chain.wallets == []
    _run(runner)
    assert chain.log == _expected(network, B)
    assert _wallets(chain) == {B}


def test_a_session_submitted_after_set_private_key_is_the_new_wallets(chain, monkeypatch):
    monkeypatch.setattr(session_module, "EthernityCloudSession",
                        lambda runner, order_id: SimpleNamespace(order_id=order_id))
    runner = _runner(AMOY, key=KEY_A)
    runner.set_private_key(KEY_B)
    assert runner.run_session(RESOURCES, SECURELOCK, "v3", "code").order_id == ORDER
    assert chain.log == _expected(AMOY, B)
    assert _wallets(chain) == {B}


def test_a_read_outside_a_run_is_made_from_the_new_wallet(chain):
    runner = _runner(AMOY, key=KEY_A)
    runner.set_private_key(KEY_B)
    assert runner.list_sessions() == []
    assert chain.wallets == [("call", B)]


# ---- what the runner holds after a change of the wallet ----

@EVERY_NETWORK
def test_a_connected_runner_holds_a_contract_of_its_network_for_the_new_wallet(chain, network):
    runner = _runner(network, key=KEY_A)
    left, storage = runner.contract, runner.ipfs_client
    assert runner.contract.signer.address == A
    runner.set_private_key(KEY_B)
    entry = _entry(network)
    assert _is_wallet_of(runner, KEY_B)
    assert runner.signer.address == B
    assert runner.contract is not left
    assert runner.contract.signer is runner.signer
    assert runner.contract.get_signer() is runner.signer
    assert runner.contract.get_current_wallet() is runner.signer
    assert runner.contract.network_config is entry
    assert runner.contract.provider.provider.url == entry.RPC_URL
    assert runner.protocol_contract is runner.contract.protocol_contract
    assert runner.protocol_contract.address == entry.PROTOCOL_ADDRESS
    assert runner.token_contract is runner.contract.token_contract
    assert runner.token_contract.address == entry.TOKEN_ADDRESS
    # The network and the storage are the runner's as before.
    assert (runner.network_name, runner.network_type) == network
    assert runner.network_config is entry
    assert runner.trustedZoneImage == entry.TRUSTEDZONE_IMAGE
    assert runner.ipfs_client is storage
    assert chain.log == []


def test_the_wallet_left_keeps_nothing_in_hand(chain):
    runner = _runner(AMOY, key=KEY_A)
    runner.set_max_fee_per_gas(600)
    cache = runner.enable_state_cache(backend={})
    _run(runner)
    # What a request of the runner's own leaves beside the order: its challenge, the block it was sent
    # at, the order count it was sent after and its hash.
    runner.challenge_hash, runner.request_start_block, runner.current_order_index = b"challenge", 53_000_000, 41
    runner.do_request, runner.do_hash = 40, TX
    runner._esr_wallet_memo[SECURELOCK] = "0x" + "ee" * 20
    assert runner.image_registry_contract is not None
    assert runner.image_registry_contract.get_signer().address == A
    assert (runner.order_id, runner.node_address) == (ORDER, "0x" + "00" * 20)
    runner.set_private_key(KEY_B)
    assert runner.image_registry_contract is None
    assert (runner.order, runner.order_id, runner.do_request, runner.do_hash) == (None, -1, -1, None)
    assert (runner.challenge_hash, runner.request_start_block, runner.current_order_index) == (b"", None, 0)
    assert runner.node_address == ""
    # The network's and the enclave's, and the runner's settings and last outcome, stay.
    assert (runner.enclave_image_ipfs_hash, runner.enclave_public_key,
            runner.enclave_docker_compose_ipfs_hash) == ("QmSecurelock", "trustedzone certificate", "QmCompose")
    assert runner._esr_wallet_memo == {SECURELOCK: "0x" + "ee" * 20}
    assert runner.state_cache is cache
    assert runner.contract.fee_ceiling() == (600 * 10 ** 9, "set with set_max_fee_per_gas")
    assert runner.get_result()["value"] == "ok"
    assert runner.status == ECStatus.SUCCESS
    assert runner.resources == RESOURCES
    assert (runner.securelock_enclave, runner.securelock_version) == (SECURELOCK, "v3")


def test_an_unconnected_runner_takes_the_wallet_without_a_contract_and_connects_with_it(chain):
    runner = _runner(AMOY, connect=False, key=KEY_A)
    runner.set_private_key(KEY_B)
    assert runner.signer.address == B
    assert (runner.contract, runner.protocol_contract, runner.token_contract) == (None, None, None)
    runner.connect()
    assert runner.contract.signer is runner.signer
    _run(runner)
    assert chain.log == _expected(AMOY, B)
    assert _wallets(chain) == {B}


def test_the_same_key_again_keeps_the_wallet_and_drops_its_order(chain):
    runner = _runner(AMOY, key=KEY_A)
    _run(runner)
    runner.set_private_key(KEY_A)
    assert runner.signer.address == A
    assert runner.contract.signer is runner.signer
    assert (runner.order_id, runner.image_registry_contract) == (-1, None)


# ---- a call that raises changes nothing ----

def test_set_private_key_is_refused_while_a_run_is_in_progress(chain):
    runner = _runner(AMOY, key=KEY_A)
    reached, release = threading.Event(), threading.Event()

    def process_task():
        reached.set()
        assert release.wait(10)
        return {"success": True, "result_task_code": "SUCCESS", "result_task_code_int": 0, "value": "ok"}

    runner.process_task = process_task
    runner.run(RESOURCES, SECURELOCK, "v3", "code")
    try:
        assert reached.wait(10)
        held = _held(runner)
        with pytest.raises(RuntimeError) as refusal:
            runner.set_private_key(KEY_B)
        assert str(refusal.value) == IN_PROGRESS
        assert _held(runner) == held
        assert _is_wallet_of(runner, KEY_A)
    finally:
        release.set()
        runner.task_thread.join(10)
    assert runner.status == ECStatus.SUCCESS
    assert chain.log == _expected(AMOY, A)
    assert _wallets(chain) == {A}
    # The run has ended: the wallet is taken.
    runner.set_private_key(KEY_B)
    assert runner.contract.signer.address == B


def test_set_private_key_is_refused_while_a_session_is_open(chain, monkeypatch):
    monkeypatch.setattr(session_module, "EthernityCloudSession",
                        lambda runner, order_id: SimpleNamespace(order_id=order_id))
    runner = _runner(AMOY, key=KEY_A)
    runner.run_session(RESOURCES, SECURELOCK, "v3", "code")
    held = _held(runner)
    with pytest.raises(RuntimeError) as refusal:
        runner.set_private_key(KEY_B)
    assert str(refusal.value) == IN_PROGRESS
    assert _held(runner) == held
    assert _is_wallet_of(runner, KEY_A)
    assert runner.is_running()


def test_set_private_key_is_refused_while_a_submission_holds_the_runners_lock(chain):
    runner = _runner(AMOY, key=KEY_A)
    held = _held(runner)
    with runner._run_lock:
        assert not runner.is_running()
        with pytest.raises(RuntimeError) as refusal:
            runner.set_private_key(KEY_B)
    assert str(refusal.value) == IN_PROGRESS
    assert _held(runner) == held
    assert _is_wallet_of(runner, KEY_A)
    runner.set_private_key(KEY_B)
    assert not runner._run_lock.locked()
    assert runner.signer.address == B


@pytest.mark.parametrize("connect", [True, False], ids=["connected", "unconnected"])
@pytest.mark.parametrize("given", [NOT_0X, TOO_SHORT], ids=["no 0x", "62 digits"])
def test_a_string_of_another_form_leaves_the_runner_with_its_wallet(chain, connect, given):
    runner = _runner(AMOY, connect=connect, key=KEY_A)
    held = _held(runner)
    with pytest.raises(ValueError, match="^Invalid private key format. Must be 64 hex chars prefixed with 0x.$"):
        runner.set_private_key(given)
    assert _held(runner) == held
    assert _is_wallet_of(runner, KEY_A)


@pytest.mark.parametrize("connect", [True, False], ids=["connected", "unconnected"])
@pytest.mark.parametrize("given", [NOT_HEX, ABOVE_THE_CURVE_ORDER], ids=["not hex", "above the curve order"])
def test_a_key_eth_account_does_not_take_leaves_the_runner_with_its_wallet(chain, connect, given):
    runner = _runner(AMOY, connect=connect, key=KEY_A)
    held = _held(runner)
    with pytest.raises(Exception) as refusal:
        runner.set_private_key(given)
    names_it = given in str(refusal.value) or given[2:] in str(refusal.value)
    assert not names_it
    assert _held(runner) == held
    assert _is_wallet_of(runner, KEY_A)
    assert runner.signer.address == A


# ---- no key in a log line, an exception text or a repr ----

def _forms(key):
    """What a text that prints a key, or half of one, holds: each half of its 64 digits in either case, and
    each half of its 32 bytes as Python prints bytes."""
    digits = key[2:]
    halves = (digits[:32], digits[32:])
    return ({half for half in halves} | {half.upper() for half in halves}
            | {repr(bytes.fromhex(half))[2:-1] for half in halves})


def test_no_log_line_exception_text_or_repr_holds_a_key(chain, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    texts = {}
    runner = _runner(AMOY, key=KEY_A)
    runner.set_log_level("DEBUG")
    _run(runner)
    runner.set_private_key(KEY_B)
    _run(runner)
    for name, call in {
        "the refusal during a submission": lambda: runner.set_private_key(KEY_A),
        "the refusal of set_network during a submission": lambda: runner.set_network(*AMOY_POX10),
    }.items():
        with runner._run_lock, pytest.raises(RuntimeError) as refusal:
            call()
        texts[name] = f"{refusal.value} {refusal.value!r}"
    for name, given in {"a key without 0x": KEY_A[2:] + "00", "a key cut short": KEY_A[:-2],
                        "a key with a digit that is none": KEY_A[:-1] + "z"}.items():
        with pytest.raises(Exception) as refusal:
            runner.set_private_key(given)
        texts[name] = f"{refusal.value} {refusal.value!r}"
    captured = capsys.readouterr()
    texts.update({
        "the log": caplog.text, "stdout": captured.out, "stderr": captured.err,
        "repr(runner)": repr(runner), "str(runner)": str(runner),
        "repr(runner.contract)": repr(runner.contract), "repr(runner.signer)": repr(runner.signer),
        "repr(runner.protocol_contract)": repr(runner.protocol_contract),
        "the state": repr(runner.get_state()), "the result": repr(runner.get_result()),
    })
    assert caplog.text and "balance" in caplog.text
    forms = _forms(KEY_A) | _forms(KEY_B)
    holding = sorted(name for name, text in texts.items() if any(form in text for form in forms))
    assert holding == []
    assert runner.signer.address == B
