"""close() and the calls that change or use the runner from other threads.

close() is serialised with connect(), set_network() and set_private_key():
a change building and assigning when close() is called is waited for, and
close() then retires what it assigned and drops the contracts, the signer
and the key, so no protocol contract close() did not retire is left and no
key comes back; a change that waited for close() does nothing and raises
CLOSED_WHILE_WAITING, as do connect(), run(), run_session() and
attach_session() when they waited for the runner's lock while close() was
called. A transaction being handed to the node when close() is called is
handed over before close() returns, and none is sent after. A ceiling set
with set_max_fee_per_gas is that of every protocol contract of the runner,
the one a run began with and the one a handle was made with included. A
session handle whose close(wait=True) returned the summary is out of the
runner's handles. The thread of an attempt takes its events without waiting,
so a queue close() empties never blocks it.

No chain: the contracts, the provider and the stand-ins of a run are
test_set_network.py's, the session handles are the real ones."""
import threading
from queue import Queue

import pytest

import test_set_network
from ethernity_cloud_runner_py.enums import ECStatus
from ethernity_cloud_runner_py.errors import FeeCeilingError, RunEndedError
from ethernity_cloud_runner_py.runner import CLOSED_WHILE_WAITING, EthernityCloudRunner

from test_set_network import (  # noqa: F401 (chain is the fixture the cases ask for)
    AMOY, AMOY_POX10, KEY, ORDER, RESOURCES, SECURELOCK, WALLET, _expected, _run, _runner, chain,
)
from test_runner_lifetime import (
    CLOSE, DO_REQUEST, DP_REQUEST, NODE, OTHER_KEY, SWITCHES, _Hold, _held_run, _in_session, _open, _read_of, _row,
    _sends,
)

# The three calls that change the runner's contract, network or key, by the name their refusal gives them.
CHANGES = {
    "connect()": lambda runner: runner.connect(),
    "set_network()": lambda runner: runner.set_network(*AMOY_POX10),
    "set_private_key()": lambda runner: runner.set_private_key(OTHER_KEY),
}
EVERY_CHANGE = pytest.mark.parametrize("call", list(CHANGES))


def _in_a_thread(call, outcome, name):
    """A started thread that makes `call` and keeps what it raised, or None, in outcome[name]."""
    def work():
        try:
            call()
            outcome[name] = None
        except Exception as raised:
            outcome[name] = raised

    thread = threading.Thread(target=work)
    thread.start()
    return thread


def _building_held(runner):
    """Holds the next _protocol_contract call of the runner, in the thread that makes it, once it has built
    its contract: (reached, release, built), built listing what it built."""
    build = runner._protocol_contract
    reached, release, built = threading.Event(), threading.Event(), []

    def held(*arguments):
        contract = build(*arguments)
        built.append(contract)
        if not reached.is_set():
            reached.set()
            assert release.wait(10)
        return contract

    runner._protocol_contract = held
    return reached, release, built


def _closed_and_keyless(runner):
    return (runner.contract, runner.signer, runner.private_key, runner.token_contract, runner.protocol_contract) == (
        None, None, "", None, None)


# ---- close() during a change ----

@EVERY_CHANGE
def test_close_waits_for_a_change_building_its_contract_and_retires_what_it_assigned(chain, call):
    runner = _runner(AMOY)
    reached, release, built = _building_held(runner)
    outcome = {}
    changing = _in_a_thread(lambda: CHANGES[call](runner), outcome, "change")
    try:
        assert reached.wait(10)
        closing = _in_a_thread(runner.close, outcome, "close")
        closing.join(0.5)
        waited = closing.is_alive()
    finally:
        release.set()
        changing.join(10)
        closing.join(10)
    assert waited
    # The change was made before close(), which ended what it assigned.
    assert outcome == {"change": None, "close": None}
    assert len(built) == 1 and built[0].retired == "The runner was closed with close()"
    assert _closed_and_keyless(runner)
    with pytest.raises(RunEndedError):
        built[0].approve_order(ORDER)
    assert _sends(chain) == []


def test_close_waits_for_a_set_network_in_its_round_trip_to_the_network_set(chain):
    """set_network() is held in the provider's answer to is_connected of the network it moves the runner to,
    the round trip of a public RPC."""
    runner = _runner(AMOY)
    left, build, built = runner.contract, runner._protocol_contract, []
    runner._protocol_contract = lambda *arguments: built.append(build(*arguments)) or built[-1]
    hold = _Hold(chain, lambda url, method, params: method == "is_connected")
    outcome = {}
    switching = _in_a_thread(lambda: runner.set_network(*AMOY_POX10), outcome, "switch")
    try:
        assert hold.reached.wait(10)
        closing = _in_a_thread(runner.close, outcome, "close")
        closing.join(0.5)
        waited = closing.is_alive()
    finally:
        hold.release()
        switching.join(10)
        closing.join(10)
    assert waited
    assert outcome == {"switch": None, "close": None}
    assert (runner.network_name, runner.network_type) == AMOY_POX10
    assert _closed_and_keyless(runner)
    # Neither the contract of the network left nor the one set_network() built sends.
    assert len(built) == 1 and built[0].network_config is runner.network_config
    assert built[0].retired == "The runner was closed with close()"
    for contract in (left, built[0]):
        with pytest.raises(RunEndedError):
            contract.approve_order(ORDER)
    assert _sends(chain) == []


@EVERY_CHANGE
def test_a_change_that_waited_for_close_does_nothing(chain, call):
    """close() is held while it retires the runner's contract; the change, called meanwhile, waits for it
    and raises."""
    runner = _runner(AMOY)
    contract = runner.contract
    retire = contract.retire
    reached, release = threading.Event(), threading.Event()

    def held_retire(reason):
        reached.set()
        assert release.wait(10)
        retire(reason)

    contract.retire = held_retire
    outcome = {}
    closing = _in_a_thread(runner.close, outcome, "close")
    try:
        assert reached.wait(10)
        changing = _in_a_thread(lambda: CHANGES[call](runner), outcome, "change")
        changing.join(0.5)
        waited = changing.is_alive()
    finally:
        release.set()
        closing.join(10)
        changing.join(10)
    assert waited
    assert outcome["close"] is None
    assert type(outcome["change"]) is RuntimeError
    assert str(outcome["change"]) == CLOSED_WHILE_WAITING.format(call=call)
    assert (runner.network_name, runner.network_type) == AMOY
    assert _closed_and_keyless(runner)
    assert not runner._run_lock.locked() and not runner._change_lock.locked()
    # A call made after close() returned is taken.
    runner.set_private_key(KEY)
    runner.connect()
    assert runner.contract.retired is None


def test_the_message_of_a_call_that_waited_for_close():
    assert CLOSED_WHILE_WAITING.format(call="set_network()") == (
        "The runner was closed with close() while set_network() waited for it: set_network() did nothing. A "
        "closed runner takes a key with set_private_key() and connect() again; another EthernityCloudRunner "
        "serves meanwhile.")


# ---- the calls that waited for the runner's lock while close() was called ----

LOCK_TAKERS = {
    "connect()": lambda runner: runner.connect(),
    "run()": lambda runner: runner.run(RESOURCES, SECURELOCK, "v3", "code"),
    "run_session()": lambda runner: runner.run_session(RESOURCES, SECURELOCK, "v3", "code"),
    "attach_session()": lambda runner: runner.attach_session(ORDER),
}


@pytest.mark.parametrize("call", list(LOCK_TAKERS))
def test_a_call_that_waited_behind_a_submission_close_ended_does_nothing(chain, call):
    """A run_session() of another thread holds the runner's lock, held in its balance read; the call waits for
    the lock, close() ends the submission, and the call raises once it has the lock. An attach_session() of
    that kind names no change of the network or the wallet: the runner was closed."""
    _in_session(chain)
    runner = _runner(AMOY)
    runner.block_time = 0.05
    hold = _Hold(chain, _read_of("balanceOf"))
    outcome = {}
    submitting = _in_a_thread(lambda: runner.run_session(RESOURCES, SECURELOCK, "v3", "code"), outcome, "submission")
    try:
        assert hold.reached.wait(10)
        waiting = _in_a_thread(lambda: LOCK_TAKERS[call](runner), outcome, "call")
        waiting.join(0.3)
        waited = waiting.is_alive()
        runner.close()
    finally:
        hold.release()
        submitting.join(10)
        waiting.join(10)
    assert waited
    assert isinstance(outcome["submission"], RunEndedError)
    assert type(outcome["call"]) is RuntimeError
    assert str(outcome["call"]) == CLOSED_WHILE_WAITING.format(call=call)
    assert runner.task_thread is None
    assert _sends(chain) == []
    assert not runner._run_lock.locked()


# ---- a transaction being handed to the node ----

def test_close_waits_for_a_transaction_being_handed_to_the_node_and_none_is_sent_after(chain):
    runner = _runner(AMOY)
    thread, hold = _held_run(chain, runner, lambda url, method, params: method == "eth_sendRawTransaction")
    outcome = {}
    sent_when_closed = []

    def close():
        runner.close()
        sent_when_closed.append(len(_sends(chain)))

    closing = _in_a_thread(close, outcome, "close")
    try:
        closing.join(0.5)
        waited = closing.is_alive()
    finally:
        hold.release()
        closing.join(10)
        thread.join(10)
    assert waited
    assert outcome == {"close": None}
    # The approval was handed over before close() returned, and nothing was sent after it.
    assert sent_when_closed == [1]
    assert [entry[4] for entry in _sends(chain)] == ["approve"]
    assert not thread.is_alive()


def test_retire_takes_the_lock_a_send_holds_while_it_hands_its_transaction_over(chain):
    runner = _runner(AMOY)
    contract = runner.contract
    hold = _Hold(chain, lambda url, method, params: method == "eth_sendRawTransaction")
    outcome = {}
    sending = _in_a_thread(lambda: contract.approve_order(ORDER), outcome, "send")
    try:
        assert hold.reached.wait(10)
        retiring = _in_a_thread(lambda: contract.retire("Retired"), outcome, "retire")
        retiring.join(0.3)
        waited = retiring.is_alive()
    finally:
        hold.release()
        sending.join(10)
        retiring.join(10)
    assert waited
    assert outcome == {"send": None, "retire": None}
    with pytest.raises(RunEndedError):
        contract.approve_order(ORDER)
    assert len(_sends(chain)) == 1


def test_a_contract_keeps_the_reason_it_was_first_retired_for(chain):
    runner = _runner(AMOY)
    left = runner.contract
    runner.set_network(*AMOY_POX10)
    runner.close()
    assert left.retired == "The runner was moved to POLYGON AMOY_POX10 with set_network()"
    assert all(contract.retired is not None for contract in list(runner._contracts))


# ---- the fee ceiling of the contracts a run and a handle hold ----

CEILING_50 = "is above the fee ceiling of 50 gwei (set with set_max_fee_per_gas)"


def test_a_ceiling_set_after_a_connect_is_that_of_a_handle_made_before_it(chain):
    """The base fee is 20 gwei: a row's maxFeePerGas is 54 gwei, above a ceiling of 50."""
    _in_session(chain)
    runner = _runner(AMOY)
    session = _open(runner)
    runner.connect()
    assert session._contract is not runner.contract
    runner.set_max_fee_per_gas(50)
    mark = len(chain.log)
    with pytest.raises(FeeCeilingError) as refused:
        session.close(wait=False)
    assert CEILING_50 in str(refused.value)
    assert _sends(chain, mark) == []


def test_a_raised_ceiling_reaches_a_handle_made_before_a_connect(chain, monkeypatch):
    """The base fee is 600 gwei: a row's maxFeePerGas is 692 gwei, above the network's 500 and within a
    ceiling of 1000 set after the connect()."""
    _in_session(chain)
    runner = _runner(AMOY)
    session = _open(runner)
    runner.connect()
    monkeypatch.setattr(test_set_network, "BASE_FEE", 600 * 10 ** 9)
    runner.set_max_fee_per_gas(1000)
    mark = len(chain.log)
    session.close(wait=False)
    assert _sends(chain, mark) == [_row(AMOY, CLOSE)]


def test_a_ceiling_set_after_a_connect_is_that_of_a_run_that_began_before_it(chain):
    runner = _runner(AMOY)
    thread, hold = _held_run(chain, runner, _read_of("allowance"))
    try:
        runner.connect()
        assert runner._run.contract is not runner.contract
        runner.set_max_fee_per_gas(50)
    finally:
        hold.release()
        thread.join(10)
    assert runner.status == ECStatus.ERROR
    assert CEILING_50 in runner.last_error
    assert _sends(chain) == []


def test_a_contract_built_later_holds_the_ceiling_set(chain):
    runner = _runner(AMOY)
    runner.set_max_fee_per_gas(50)
    runner.set_network(*AMOY_POX10)
    assert runner.contract.max_fee_per_gas == 50


# ---- the events of an attempt ----

class _EmptiedMeanwhile(Queue):
    """A queue whose empty() answers False while it holds nothing: the answer a thread had just before close()
    emptied the queue."""

    def empty(self):
        return False


def test_an_attempt_whose_queue_was_emptied_meanwhile_ends():
    runner = EthernityCloudRunner(*AMOY)
    runner.running = True
    runner.event_queue = _EmptiedMeanwhile()
    attempt = threading.Thread(target=runner._run_attempt, args=("code", "", RESOURCES), daemon=True)
    attempt.start()
    attempt.join(2)
    assert not attempt.is_alive()
    assert runner.processed_events == []


def test_close_empties_the_queue_whatever_another_thread_does_with_it():
    runner = EthernityCloudRunner(*AMOY)
    runner.event_queue = _EmptiedMeanwhile()
    runner.close()
    assert runner.event_queue.qsize() == 0 and type(runner.event_queue) is Queue


# ---- a session closed with wait=True ----

SUMMARY = {"success": True, "result_task_code": "SUCCESS", "result_task_code_int": 0, "value": "the summary"}


def _settles_on_its_close_row(chain):
    """The order of the session is PROCESSING until its close row is sent, and CLOSED after it."""
    def order(arguments):
        closed = any(entry[0] == "send" and entry[4] == "_addMetadataToRequest" and entry[5][2] == CLOSE
                     for entry in chain.log)
        return [WALLET, NODE, DO_REQUEST, DP_REQUEST, 2 if closed else 1]

    chain.answers["_getOrder"] = order


def _summarizing(runner):
    """The runner's final result read answers SUMMARY; returns the order ids it was asked for."""
    asked = []
    runner.get_result_from_order = lambda order_id: asked.append(order_id) or dict(SUMMARY)
    return asked


def test_a_session_closed_with_wait_leaves_the_runner_to_change_and_run(chain):
    _in_session(chain)
    _settles_on_its_close_row(chain)
    runner = _runner(AMOY)
    asked = _summarizing(runner)
    session = _open(runner)
    assert session.close(wait=True) == SUMMARY
    assert runner._sessions == [] and runner.is_running() is False
    # A later close(wait=True) of the handle returns the summary and reads nothing.
    mark = len(chain.log)
    assert session.close(wait=True) == SUMMARY
    assert session.close(wait=False) is None
    assert chain.log[mark:] == [] and asked == [ORDER]
    runner.set_private_key(OTHER_KEY)
    runner.set_private_key(KEY)
    runner.set_network(*AMOY_POX10)
    runner.connect()
    del chain.log[:]
    _run(runner)
    assert chain.log == _expected(AMOY_POX10)


def test_a_session_closed_without_wait_keeps_the_runner_until_a_close_with_wait(chain):
    _in_session(chain)
    _settles_on_its_close_row(chain)
    runner = _runner(AMOY)
    _summarizing(runner)
    session = _open(runner)
    assert session.close(wait=False) is None
    change, refused = SWITCHES["set_network"]
    with pytest.raises(RuntimeError) as refusal:
        change(runner)
    assert str(refusal.value) == refused
    assert session.close(wait=True) == SUMMARY
    change(runner)
    assert (runner.network_name, runner.network_type) == AMOY_POX10


def test_a_runner_stays_in_progress_for_the_handles_it_still_holds(chain):
    _in_session(chain)
    _settles_on_its_close_row(chain)
    runner = _runner(AMOY)
    _summarizing(runner)
    first, second = _open(runner), _open(runner)
    assert first.close(wait=True) == SUMMARY
    assert runner._sessions == [second] and runner.is_running() is True
    change, refused = SWITCHES["set_private_key"]
    with pytest.raises(RuntimeError) as refusal:
        change(runner)
    assert str(refusal.value) == refused
    assert second.close(wait=True) == SUMMARY
    change(runner)
    assert runner.is_running() is False
