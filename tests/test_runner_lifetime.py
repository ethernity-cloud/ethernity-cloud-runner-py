"""What outlives a call of an EthernityCloudRunner, and what it may do then.

A session handle works through the protocol contract, the certificate and
the wallet key the runner held when the handle was made, and the runner's
close() detaches it: it sends nothing after that, whatever network or wallet
the runner is given next. set_network() and set_private_key() are refused for
what is alive (an open handle, a run whose thread is at work, a submission
under way), not for the running flag alone, and attach_session() and
connect() work under the runner's lock as run() and run_session() do; an
attach_session() that waited for a change of the network or the wallet is
refused, since its order id was given for the network and the wallet the
runner had. The thread of a run that close() ended sends no transaction and
tries nothing again, and the runner takes no network, wallet, connection,
run or session until that thread has ended: the next call waits for it
RUN_END_WAIT_SECONDS and raises after that.

No chain: the contracts, the provider that keeps every read and transaction
and the steps of a run after its request are test_set_network.py's; the
session handles are the real ones."""
import threading
import time
from types import SimpleNamespace

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

import ethernity_cloud_runner_py.ipfs as ipfs_module
import ethernity_cloud_runner_py.runner as runner_module
import ethernity_cloud_runner_py.session as session_module
from ethernity_cloud_runner_py.enums import ECNetwork, ZERO_CHECKSUM
from ethernity_cloud_runner_py.errors import RunEndedError
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from ethernity_cloud_runner_py.session import EthernityCloudSession, SessionError

from test_set_network import (  # noqa: F401 (chain is the fixture the cases ask for)
    AMOY, AMOY_POX10, KEY, ORDER, RESOURCES, REVERTS, SECURELOCK, WALLET,
    _called, _entry, _expected, _held, _run, _runner, chain,
)

# A second wallet, of a key generated when the module is loaded and compared in no assert.
OTHER_KEY = "0x" + bytes(Account.create().key).hex()
OTHER = Account.from_key(OTHER_KEY).address
NODE = Web3.to_checksum_address("0x" + "22" * 20)
DO_REQUEST, DP_REQUEST = 41, 5
UNREGISTERED = "a-securelock-the-registry-does-not-hold"
CLOSE = f"v1:close:{ORDER}"

DETACHED = ("The runner was closed with close(): this handle of a session on POLYGON AMOY sends and reads nothing "
            "more. The session's order stays as it is on chain; attach_session(order_id) on a connected runner "
            "of that network and wallet gives a new handle.")
RUN_ENDED = ("The runner was closed with close() while this run or session submission was in progress: it has "
             "ended, and nothing more of it is sent.")
STILL_AT_WORK = ("The run this runner was closed during is still at work in its thread, which was waited for "
                 "0.2 s: {call} is refused until that thread has ended. The thread sends no transaction. Call "
                 "again later, or use another EthernityCloudRunner.")


def _in_progress(call, instead):
    return (f"A run or a session of this runner is in progress on POLYGON AMOY: {call} is refused until the run "
            f"has ended or, after a session, the runner is closed with close(). {instead}")


# The two changes of a runner, each with the text of its refusal on POLYGON AMOY.
SWITCHES = {
    "set_network": (lambda runner: runner.set_network(*AMOY_POX10),
                    _in_progress("set_network()", "Use another EthernityCloudRunner for POLYGON AMOY_POX10.")),
    "set_private_key": (lambda runner: runner.set_private_key(OTHER_KEY),
                        _in_progress("set_private_key()", "Use another EthernityCloudRunner for another wallet.")),
}
EVERY_SWITCH = pytest.mark.parametrize("switch", list(SWITCHES))


def _in_session(chain, wallet=WALLET, network=AMOY):
    """The chain answers for order ORDER as a session of `wallet` in progress: its request DO_REQUEST of one
    hour, marked v3s, taken by NODE on DP_REQUEST, with the trustedzone of `network` in its image metadata."""
    trustedzone = _entry(network).TRUSTEDZONE_IMAGE
    chain.answers.update({
        "_getOrder": [wallet, NODE, DO_REQUEST, DP_REQUEST, 1],
        "_getDORequest": [wallet, 1, 1, 40, 1, 1, 3, 0],
        "_getDORequestMetadata": [wallet, f"v3:QmImage:{trustedzone}:QmCompose:QmChallenge:0xkey",
                                  f"v3:QmCode:{ZERO_CHECKSUM}", f"v3s::{ZERO_CHECKSUM}", ""],
    })


def _open(runner):
    """A session of the runner, submitted with run_session(): its handle."""
    session = runner.run_session(RESOURCES, SECURELOCK, "v3", "code")
    assert isinstance(session, EthernityCloudSession)
    return session


def _sends(chain, start=0):
    return [entry for entry in chain.log[start:] if entry[0] == "send"]


def _row(network, value):
    """The transaction of a session row `value` on DO_REQUEST at the PoX of `network`."""
    entry = _entry(network)
    return ("send", entry.RPC_URL, entry.CHAIN_ID, Web3.to_checksum_address(entry.PROTOCOL_ADDRESS),
            "_addMetadataToRequest", (DO_REQUEST, "etny-si", value))


def _pox(network):
    return Web3.to_checksum_address(_entry(network).PROTOCOL_ADDRESS)


def _contract_of(entry):
    """The contract a kept read or transaction names."""
    return entry[2] if entry[0] == "read" else entry[3]


class _Hold:
    """Holds the first request `picks` chooses, in the thread that makes it, until release()."""

    def __init__(self, chain, picks):
        self.reached, self.released = threading.Event(), threading.Event()
        self._armed = True

        def hook(url, method, params):
            if self._armed and picks(url, method, params):
                self._armed = False
                self.reached.set()
                assert self.released.wait(30)

        chain.hooks.append(hook)

    def release(self):
        self.released.set()


def _off_the_main_thread(url, method, params):
    return method == "eth_call" and threading.current_thread() is not threading.main_thread()


def _read_of(name):
    """Picks the read of the function `name`."""
    def picks(url, method, params):
        return method == "eth_call" and _called(
            params[0]["to"], params[0].get("data") or params[0]["input"])[1]["name"] == name
    return picks


def _held_run(chain, runner, picks=_off_the_main_thread):
    """A run of the runner whose thread is held in the request `picks` chooses: (thread, hold). The runner's
    close() gives the thread a tenth of a second."""
    runner.block_time = 0.05
    hold = _Hold(chain, picks)
    runner.run(RESOURCES, SECURELOCK, "v3", "code")
    assert hold.reached.wait(10)
    return runner.task_thread, hold


# ---- the runner's lock ----

def test_the_runners_lock_is_made_with_the_runner_and_stays_the_same(chain):
    assert not EthernityCloudRunner(*AMOY)._run_lock.locked()
    _in_session(chain)
    runner = _runner(AMOY)
    lock = runner._run_lock
    _run(runner)
    runner.set_network(*AMOY_POX10)
    runner.set_private_key(KEY)
    runner.connect()
    _open(runner)
    assert runner._run_lock is lock
    assert not lock.locked()


def test_a_submission_leaves_nothing_of_itself_in_the_thread_that_made_it(chain):
    """The thread that called run_session() or attach_session() works for no run afterwards: what it sends
    goes through the contract the runner holds, and the runner keeps no mark of the call for that thread."""
    _in_session(chain)
    chain.answers["getLatestImageVersionPublicKey"] = lambda arguments: (
        REVERTS if arguments[0] == UNREGISTERED else ["QmSecurelock", "securelock certificate", "QmCompose"])
    runner = _runner(AMOY)
    fresh = vars(runner._calling).copy()
    _open(runner)
    runner.attach_session(ORDER)
    with pytest.raises(ValueError, match="^Unable to find enclave in registry$"):
        runner.attach_session(ORDER, UNREGISTERED)
    assert vars(runner._calling) == fresh == {}
    assert runner._run is None
    assert runner._sender() is runner.contract


# ---- an open session keeps the runner in progress ----

FAILURES = {
    "a second run_session": lambda runner, session: runner.run_session(RESOURCES, UNREGISTERED, "v3", "code"),
    "an attach_session": lambda runner, session: runner.attach_session(session.order_id, UNREGISTERED),
}


@EVERY_SWITCH
@pytest.mark.parametrize("failure", list(FAILURES))
def test_a_session_stays_in_progress_after_a_later_submission_of_its_runner_failed(chain, failure, switch):
    _in_session(chain)
    chain.answers["getLatestImageVersionPublicKey"] = lambda arguments: (
        REVERTS if arguments[0] == UNREGISTERED else ["QmSecurelock", "securelock certificate", "QmCompose"])
    runner = _runner(AMOY)
    session = _open(runner)
    with pytest.raises(ValueError, match="^Unable to find enclave in registry$"):
        FAILURES[failure](runner, session)
    assert runner.is_running()
    change, refused = SWITCHES[switch]
    held = _held(runner)
    with pytest.raises(RuntimeError) as refusal:
        change(runner)
    assert str(refusal.value) == refused
    assert _held(runner) == held
    # The session's close row goes to the PoX of its network, signed by its wallet.
    mark = len(chain.log)
    del chain.wallets[:]
    session.close(wait=False)
    assert _sends(chain, mark) == [_row(AMOY, CLOSE)]
    assert {wallet for _, wallet in chain.wallets} == {WALLET}


@EVERY_SWITCH
def test_the_refusal_rests_on_the_open_handle_not_on_the_running_flag(chain, switch):
    _in_session(chain)
    runner = _runner(AMOY)
    _open(runner)
    runner.running = False
    change, refused = SWITCHES[switch]
    with pytest.raises(RuntimeError) as refusal:
        change(runner)
    assert str(refusal.value) == refused


@pytest.mark.parametrize("failure", ["run_session", "attach_session"])
def test_a_submission_that_fails_on_an_idle_runner_leaves_it_idle(chain, failure):
    _in_session(chain)
    chain.answers["getLatestImageVersionPublicKey"] = REVERTS
    runner = _runner(AMOY)
    with pytest.raises(ValueError, match="^Unable to find enclave in registry$"):
        if failure == "run_session":
            runner.run_session(RESOURCES, UNREGISTERED, "v3", "code")
        else:
            runner.attach_session(ORDER, UNREGISTERED)
    assert not runner.is_running()
    assert not runner._run_lock.locked()
    runner.set_network(*AMOY_POX10)
    assert (runner.network_name, runner.network_type) == AMOY_POX10


@EVERY_SWITCH
def test_a_closed_runner_takes_the_change_its_open_session_refused(chain, switch):
    _in_session(chain)
    runner = _runner(AMOY)
    session = _open(runner)
    change, _ = SWITCHES[switch]
    with pytest.raises(RuntimeError):
        change(runner)
    runner.close()
    change(runner)
    assert not session.is_running()


# ---- run(), run_session() and attach_session() while a run is in progress ----

def _run_held_in_its_task(runner):
    """A run of the runner whose thread waits in the task's result: (reached, release)."""
    reached, release = threading.Event(), threading.Event()

    def process_task():
        reached.set()
        assert release.wait(10)
        return {"success": True, "result_task_code": "SUCCESS", "result_task_code_int": 0, "value": "ok"}

    runner.process_task = process_task
    runner.run(RESOURCES, SECURELOCK, "v3", "code")
    assert reached.wait(10)
    return release


def test_a_run_refused_during_a_run_changes_nothing_of_that_run(chain):
    runner = _runner(AMOY)
    release = _run_held_in_its_task(runner)
    try:
        with pytest.raises(RuntimeError, match="^A task is already running.$"):
            runner.run({**RESOURCES, "taskPrice": 99}, "another-securelock", "v3", "code", max_retries=9,
                       retry_delay=1, input_data="another input")
        assert runner.resources == RESOURCES
        assert (runner.input_data, runner.max_retries, runner.retry_delay) == (None, 2, 30)
        assert runner.securelock_enclave == SECURELOCK
    finally:
        release.set()
        runner.task_thread.join(10)
    assert chain.log == _expected(AMOY)


@pytest.mark.parametrize("submission", ["run_session", "attach_session"])
def test_a_session_is_refused_while_a_run_is_in_progress(chain, submission):
    runner = _runner(AMOY)
    release = _run_held_in_its_task(runner)
    try:
        mark = len(chain.log)
        with pytest.raises(RuntimeError, match="^A task is already running.$"):
            if submission == "run_session":
                runner.run_session(RESOURCES, SECURELOCK, "v3", "code")
            else:
                runner.attach_session(ORDER)
        assert chain.log[mark:] == []
        assert runner.order_id == ORDER
    finally:
        release.set()
        runner.task_thread.join(10)
    assert chain.log == _expected(AMOY)


# ---- attach_session() and connect() under the runner's lock ----

def _waited_for_a_change(network, wallet):
    """The refusal of an attach_session(ORDER) asked for on POLYGON AMOY with WALLET that waited for a change
    after which the runner is on `network` with `wallet`."""
    return (f"attach_session() waited for a change of this runner, which is on {network[0]} {network[1]} with the "
            f"wallet {wallet}; order {ORDER} was asked for on POLYGON AMOY with the wallet {WALLET}, and an order "
            "id names an order of one network and one wallet. Call attach_session() again for the order meant.")


def _attach_in_a_thread(runner, outcome):
    """A thread that attaches ORDER and keeps the handle, or what the call raised, in `outcome`."""
    def attach():
        try:
            outcome["session"] = runner.attach_session(ORDER)
        except Exception as raised:
            outcome["raised"] = raised

    return threading.Thread(target=attach)


def test_an_attach_session_that_waited_for_a_set_network_is_refused_on_the_network_set(chain):
    """The network set holds an order of the same number, a session of the same wallet: the order id was
    given for the network the runner was on, and that other session is not attached."""
    _in_session(chain, network=AMOY_POX10)
    runner = _runner(AMOY)
    hold = _Hold(chain, lambda url, method, params: method == "is_connected")
    outcome = {}
    switch = threading.Thread(target=lambda: runner.set_network(*AMOY_POX10))
    attach = _attach_in_a_thread(runner, outcome)
    switch.start()
    try:
        assert hold.reached.wait(10)
        attach.start()
        attach.join(0.5)
        waiting = attach.is_alive()
    finally:
        hold.release()
        switch.join(10)
        attach.join(10)
    assert waiting
    assert (runner.network_name, runner.network_type) == AMOY_POX10
    assert list(outcome) == ["raised"]
    assert type(outcome["raised"]) is RuntimeError
    assert str(outcome["raised"]) == _waited_for_a_change(AMOY_POX10, WALLET)
    # Nothing was read for the attachment or sent, and the runner holds no handle and is idle.
    assert chain.log == []
    assert runner._sessions == []
    assert not runner.is_running()
    assert not runner._run_lock.locked()


def test_an_attach_session_that_waited_for_a_set_private_key_is_refused_for_the_wallet_set(chain):
    """The order on chain is the other wallet's session: an attachment made for the wallet set would take
    it, and the order id was given for the wallet the runner had."""
    _in_session(chain, wallet=OTHER)
    runner = _runner(AMOY)
    build = runner._protocol_contract
    reached, go = threading.Event(), threading.Event()

    def build_held(*arguments):
        reached.set()
        assert go.wait(10)
        return build(*arguments)

    runner._protocol_contract = build_held
    outcome = {}
    switching = threading.Thread(target=lambda: runner.set_private_key(OTHER_KEY))
    attaching = _attach_in_a_thread(runner, outcome)
    switching.start()
    try:
        assert reached.wait(10)
        attaching.start()
        attaching.join(0.5)
        waiting = attaching.is_alive()
    finally:
        go.set()
        switching.join(10)
        attaching.join(10)
    assert waiting
    assert runner.signer.address == OTHER
    assert list(outcome) == ["raised"]
    assert type(outcome["raised"]) is RuntimeError
    assert str(outcome["raised"]) == _waited_for_a_change(AMOY, OTHER)
    assert chain.log == []
    assert runner._sessions == []


def test_an_attach_session_that_waited_for_a_connect_attaches_once_it_is_done(chain):
    """A connect() changes neither the network nor the wallet: the attachment waits for it and is made
    through the contract it built."""
    _in_session(chain)
    runner = _runner(AMOY)
    build = runner._protocol_contract
    reached, go = threading.Event(), threading.Event()
    connecting = threading.Thread(target=runner.connect)

    def build_held_in_connect(*arguments):
        contract = build(*arguments)
        if threading.current_thread() is connecting:
            reached.set()
            assert go.wait(10)
        return contract

    runner._protocol_contract = build_held_in_connect
    outcome = {}
    attaching = _attach_in_a_thread(runner, outcome)
    connecting.start()
    try:
        assert reached.wait(10)
        attaching.start()
        attaching.join(0.5)
        waiting, read_meanwhile = attaching.is_alive(), list(chain.log)
    finally:
        go.set()
        connecting.join(10)
        attaching.join(10)
    assert waiting
    assert read_meanwhile == []
    assert list(outcome) == ["session"]
    assert outcome["session"]._contract is runner.contract
    assert {_contract_of(entry) for entry in chain.log} == {_pox(AMOY)}
    outcome["session"].close(wait=False)
    assert _sends(chain) == [_row(AMOY, CLOSE)]


def test_a_set_network_during_a_connect_is_refused_and_the_runner_stays_whole(chain):
    runner = _runner(AMOY)
    build = runner._protocol_contract
    reached, go = threading.Event(), threading.Event()
    connecting = threading.Thread(target=runner.connect)

    def build_held_in_connect(*arguments):
        contract = build(*arguments)
        if threading.current_thread() is connecting:
            reached.set()
            assert go.wait(10)
        return contract

    runner._protocol_contract = build_held_in_connect
    connecting.start()
    try:
        assert reached.wait(10)
        with pytest.raises(RuntimeError) as refusal:
            runner.set_network(*AMOY_POX10)
    finally:
        go.set()
        connecting.join(10)
    assert str(refusal.value) == SWITCHES["set_network"][1]
    assert (runner.network_name, runner.network_type) == AMOY
    assert runner.contract.network_config is runner.network_config is ECNetwork.POLYGON.AMOY
    assert not runner._run_lock.locked()


# ---- a session handle works through what it was made with ----

def test_a_handle_sends_and_reads_through_the_contract_it_was_made_with(chain):
    """Whatever contract the runner holds later: here the one a change of the network and the wallet would
    leave it, were one taken with the session open."""
    _in_session(chain)
    runner = _runner(AMOY)
    session = _open(runner)
    runner._hold_contract(runner._protocol_contract(*AMOY_POX10, Account.from_key(OTHER_KEY)))
    mark = len(chain.log)
    del chain.wallets[:]
    assert session.is_running()
    assert session.get_status()["order_status"] == 1
    session.close(wait=False)
    order_read = ("read", _entry(AMOY).RPC_URL, _pox(AMOY), "_getOrder", (ORDER,))
    assert chain.log[mark:] == [order_read, order_read, _row(AMOY, CLOSE)]
    assert {wallet for _, wallet in chain.wallets} == {WALLET}


def test_an_input_is_sealed_for_the_certificate_and_signed_with_the_key_the_handle_was_made_with(chain, monkeypatch):
    _in_session(chain)
    sealed, posts = [], []

    def encrypt(plaintext, certificate):
        sealed.append((plaintext, certificate))
        return b"sealed:" + plaintext

    def post(url, **kwargs):
        posts.append((url, kwargs))
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(runner_module, "encrypt", encrypt)
    monkeypatch.setattr(ipfs_module.requests, "post", post)
    runner = _runner(AMOY)
    runner.set_public_intake("https://intake.invalid")
    session = _open(runner)
    # What a later submission of the runner for another enclave and wallet would leave it holding.
    runner.enclave_public_key, runner.private_key = "another certificate", OTHER_KEY
    mark = len(chain.log)
    assert session.send_input("hello") == 0
    assert sealed == [(b"hello", "trustedzone certificate")]
    cid = ipfs_module.unixfs_cid(b"sealed:hello")
    url, kwargs = posts[0]
    assert len(posts) == 1
    assert url == f"https://intake.invalid/payload/polygon_amoy/{DO_REQUEST}/{cid}"
    signature = kwargs["headers"][ipfs_module.OWNER_SIGNATURE_HEADER]
    signer = Account.recover_message(encode_defunct(text=f"etny-intake|polygon_amoy|{DO_REQUEST}"),
                                     signature=bytes.fromhex(signature.removeprefix("0x")))
    assert signer == WALLET
    row = _sends(chain, mark)
    assert len(row) == 1
    assert row[0][:5] == _row(AMOY, "")[:5]
    assert row[0][5][:2] == (DO_REQUEST, "etny-si")
    assert row[0][5][2].startswith(f"v1:0:{ORDER}:{cid}:")


# ---- a handle of a closed runner ----

def _left_closed(runner):
    pass


def _moved_to_another_network(runner):
    runner.set_network(*AMOY_POX10)
    runner.set_private_key(KEY)
    runner.set_storage_ipfs("http://kubo.invalid:5001/api/v0", "writer-token")
    runner.connect()


def _given_another_wallet(runner):
    runner.set_private_key(OTHER_KEY)
    runner.set_storage_ipfs("http://kubo.invalid:5001/api/v0", "writer-token")
    runner.connect()


@pytest.mark.parametrize("afterwards", [_left_closed, _moved_to_another_network, _given_another_wallet],
                         ids=["left closed", "moved to another network", "given another wallet"])
def test_the_handle_of_a_closed_runner_sends_and_reads_nothing(chain, afterwards):
    _in_session(chain)
    runner = _runner(AMOY)
    session = _open(runner)
    runner.close()
    afterwards(runner)
    mark = len(chain.log)
    del chain.wallets[:]
    for call in (lambda: session.close(wait=False), session.close, lambda: session.send_input("hello"),
                 session.poll_outputs, lambda: session.wait_output(0, timeout=1),
                 lambda: session.wait_outputs(1, timeout=1)):
        with pytest.raises(SessionError) as refusal:
            call()
        assert str(refusal.value) == DETACHED
    assert session.closed is False
    assert session.is_running() is False
    assert (session.get_status()["order_status"], session.get_status()["running"]) == (-1, False)
    assert chain.log[mark:] == []
    assert chain.wallets == []


def test_the_handle_of_a_closed_runner_keeps_no_key(chain):
    """Whether the handle holds a key is read outside the asserts, so a failure prints none."""
    _in_session(chain)
    runner = _runner(AMOY)
    session = _open(runner)
    held_before = bool(session._private_key)
    runner.close()
    held_after = bool(session._private_key)
    assert held_before
    assert not held_after


def test_a_runner_closed_during_the_wait_of_a_close_ends_that_wait(chain, monkeypatch):
    _in_session(chain)
    runner = _runner(AMOY)
    session = _open(runner)
    clock = {"now": time.time()}

    def pause(seconds):
        """The wait's pause between two reads of the order: the moment the runner is closed."""
        clock["now"] += seconds
        runner.close()

    monkeypatch.setattr(session_module, "time", SimpleNamespace(time=lambda: clock["now"], sleep=pause))
    with pytest.raises(SessionError) as refusal:
        session.close(wait=True, timeout=900)
    assert str(refusal.value) == DETACHED
    assert session.closed is True
    assert _sends(chain)[-1] == _row(AMOY, CLOSE)


# ---- the protocol contract a runner no longer holds ----

def test_the_contract_of_a_closed_runner_sends_nothing(chain):
    runner = _runner(AMOY)
    contract = runner.contract
    runner.close()
    with pytest.raises(RunEndedError) as refusal:
        contract.add_metadata_to_request(DO_REQUEST, "etny-si", CLOSE)
    assert str(refusal.value) == ("The runner was closed with close(), and the protocol contract it held until "
                                  "then sends nothing after that: the transaction was not sent.")
    assert chain.log == [] and chain.wallets == []


@pytest.mark.parametrize("switch, reason", [
    ("set_network", "The runner was moved to POLYGON AMOY_POX10 with set_network()"),
    ("set_private_key", "The runner was given another wallet with set_private_key()"),
])
def test_the_contract_a_change_leaves_sends_nothing(chain, switch, reason):
    runner = _runner(AMOY)
    left = runner.contract
    SWITCHES[switch][0](runner)
    assert runner.contract is not left and runner.contract.retired is None
    for send in (left.faucet, lambda: left.set_allowance(3), lambda: left.approve_order(ORDER),
                 lambda: left.cancel_do_request(DO_REQUEST), lambda: left.add_do_request("i", "c", "d", "", RESOURCES)):
        with pytest.raises(RunEndedError) as refusal:
            send()
        assert str(refusal.value) == (f"{reason}, and the protocol contract it held until then sends nothing "
                                      "after that: the transaction was not sent.")
    assert chain.log == [] and chain.wallets == []
    # The contract the runner holds sends.
    runner.contract.approve_order(ORDER)
    assert len(_sends(chain)) == 1


def test_a_contract_retired_between_the_signature_and_the_send_does_not_send(chain):
    runner = _runner(AMOY)
    contract = runner.contract
    chain.hooks.append(lambda url, method, params: method == "eth_estimateGas" and contract.retire("Retired"))
    with pytest.raises(RunEndedError):
        contract.approve_order(ORDER)
    assert _sends(chain) == []


# ---- the thread of a run close() ended ----

NEXT_CALLS = {
    "set_network()": lambda runner: runner.set_network(*AMOY_POX10),
    "set_private_key()": lambda runner: runner.set_private_key(KEY),
    "connect()": lambda runner: runner.connect(),
    "run()": lambda runner: runner.run(RESOURCES, SECURELOCK, "v3", "code"),
    "run_session()": lambda runner: runner.run_session(RESOURCES, SECURELOCK, "v3", "code"),
    "attach_session()": lambda runner: runner.attach_session(ORDER),
}


def test_the_calls_after_close_are_refused_while_the_closed_runs_thread_is_at_work(chain, monkeypatch):
    monkeypatch.setattr(runner_module, "RUN_END_WAIT_SECONDS", 0.2)
    runner = _runner(AMOY)
    thread, hold = _held_run(chain, runner)
    try:
        runner.close()
        assert thread.is_alive()
        for name, call in NEXT_CALLS.items():
            with pytest.raises(RuntimeError) as refusal:
                call(runner)
            assert str(refusal.value) == STILL_AT_WORK.format(call=name)
        assert (runner.contract, runner.signer, runner.task_thread) == (None, None, None)
        assert (runner.network_name, runner.network_type) == AMOY
        assert not runner._run_lock.locked()
    finally:
        hold.release()
        thread.join(1)
        ended_at_once = not thread.is_alive()
        thread.join(10)
    assert not thread.is_alive()
    # The thread tried nothing again: its next read, through a contract the runner has dropped, fails, and
    # a run in progress would try that read twice more, two seconds apart.
    assert ended_at_once
    # The thread sent nothing and left the runner's state as close() set it.
    assert _sends(chain) == []
    assert (runner.get_state()["status"], runner.last_error, runner.is_running()) == ("SUCCESS", None, False)
    # It has ended: the runner is moved, given its key, connected and run.
    del chain.log[:]
    _moved_to_another_network(runner)
    _run(runner)
    assert chain.log == _expected(AMOY_POX10)


@pytest.mark.parametrize("call", list(NEXT_CALLS))
def test_a_call_after_close_waits_for_the_closed_runs_thread_within_the_bound(chain, monkeypatch, call):
    _in_session(chain)
    monkeypatch.setattr(runner_module, "RUN_END_WAIT_SECONDS", 20)
    runner = _runner(AMOY)
    thread, hold = _held_run(chain, runner)
    timer = threading.Timer(0.3, hold.release)
    try:
        runner.close()
        assert thread.is_alive()
        timer.start()
        raised = None
        try:
            NEXT_CALLS[call](runner)
        except Exception as error:
            raised = error
        # The call came back only once the thread, held until the timer released it, had left the run.
        waited = hold.released.is_set()
    finally:
        hold.release()
        thread.join(10)
        timer.cancel()
    assert waited
    # What a call raises on a closed runner (no key, no contract) is not the refusal of a thread at work.
    assert raised is None or "still at work" not in str(raised)
    assert _sends(chain) == []


@pytest.mark.parametrize("held_at", ["_getOrdersCount", "allowance"])
def test_a_closed_runs_thread_sends_nothing_through_a_contract_the_runner_holds_later(chain, held_at):
    """What the runner would hold were a connect() on another network taken while the thread is at work: the
    thread goes on from its read, stops at its next check (the read of the order count is followed by the
    enclave's registry entry, which a run that has ended does not read) or at its next send (the allowance
    read is followed by the approval), and sends and reads nothing."""
    runner = _runner(AMOY)
    thread, hold = _held_run(chain, runner, _read_of(held_at))
    try:
        runner.close()
        signer = Account.from_key(KEY)
        runner.signer, runner.running = signer, True
        runner._hold_contract(runner._protocol_contract(*AMOY_POX10, signer))
        mark = len(chain.log)
    finally:
        hold.release()
        thread.join(10)
    assert not thread.is_alive()
    assert _sends(chain) == []
    # The read the thread was held in is kept once it is answered; nothing follows it.
    assert [entry[3] for entry in chain.log[mark:]] == [held_at]
    assert runner.last_error is None


@pytest.mark.parametrize("held_at, cause", [("balanceOf", ValueError), ("allowance", type(None))])
def test_a_session_submission_the_runner_was_closed_during_sends_nothing(chain, held_at, cause):
    """The submission goes on from the read it was held in and ends at its next step: after the balance
    read that is the enclave's registry entry, which a submission that has ended does not read, and its
    "Unable to find enclave in registry" is the cause of the RunEndedError raised; after the allowance read
    it is the approval, which raises the RunEndedError itself."""
    runner = _runner(AMOY)
    runner.block_time = 0.05
    hold = _Hold(chain, _read_of(held_at))
    outcome = {}

    def submit():
        try:
            outcome["session"] = runner.run_session(RESOURCES, SECURELOCK, "v3", "code")
        except Exception as raised:
            outcome["raised"] = raised

    thread = threading.Thread(target=submit)
    thread.start()
    try:
        assert hold.reached.wait(10)
        runner.close()
        signer = Account.from_key(KEY)
        runner.signer = signer
        runner._hold_contract(runner._protocol_contract(*AMOY_POX10, signer))
    finally:
        hold.release()
        thread.join(10)
    assert not thread.is_alive()
    assert list(outcome) == ["raised"]
    assert isinstance(outcome["raised"], RunEndedError)
    assert str(outcome["raised"]) == RUN_ENDED
    assert type(outcome["raised"].__cause__) is cause
    assert _sends(chain) == []
    assert not runner._run_lock.locked()
    assert not runner.is_running()


def test_an_attachment_the_runner_was_closed_during_returns_no_handle(chain):
    """The attachment is held in the read of its order's request, made as its handle is built; the runner is
    closed meanwhile, and the handle is neither returned nor kept."""
    _in_session(chain)
    runner = _runner(AMOY)
    hold = _Hold(chain, _read_of("_getDORequest"))
    outcome = {}

    def attach():
        try:
            outcome["session"] = runner.attach_session(ORDER)
        except Exception as raised:
            outcome["raised"] = raised

    thread = threading.Thread(target=attach)
    thread.start()
    try:
        assert hold.reached.wait(10)
        runner.close()
    finally:
        hold.release()
        thread.join(10)
    assert not thread.is_alive()
    assert list(outcome) == ["raised"]
    assert isinstance(outcome["raised"], RunEndedError)
    assert str(outcome["raised"]) == RUN_ENDED
    assert runner._sessions == []
    assert not runner._run_lock.locked()
    assert not runner.is_running()
    # The runner takes a change at once: nothing of the attachment is in progress.
    runner.set_network(*AMOY_POX10)
    assert (runner.network_name, runner.network_type) == AMOY_POX10
