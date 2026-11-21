"""The token reads a DO request depends on: the wallet's token balance
(protocolContract.get_balance, EthernityCloudRunner._check_balance) and its
allowance for the protocol (check_allowance). A read the RPC does not answer
raises RuntimeError naming the token, the wallet and the provider's message,
never a balance of 0, which would draw the faucet on a testnet and refuse the
request as unfunded on the mainnet. Each read is tried
PRE_REQUEST_READ_ATTEMPTS times, PRE_REQUEST_READ_RETRY_SECONDS apart
(_read_before_request), and the last error is raised after that; the approve
transaction is sent once. No chain: the token contract, the signer, the faucet
and the clock are stand-ins."""
from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from web3 import Web3
from web3.exceptions import Web3RPCError

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECNetwork, ECStatus
from ethernity_cloud_runner_py.runner import (
    EthernityCloudRunner,
    PRE_REQUEST_READ_ATTEMPTS,
    PRE_REQUEST_READ_RETRY_SECONDS,
)

WALLET = "0x" + "11" * 20
TX = "0x" + "ab" * 32
TESTNET_TOKEN = ECNetwork.BLOXBERG.TESTNET.TOKEN_ADDRESS
TESTNET_PROTOCOL = ECNetwork.BLOXBERG.TESTNET.PROTOCOL_ADDRESS
MAINNET_TOKEN = ECNetwork.BLOXBERG.MAINNET.TOKEN_ADDRESS
ESCROW = 5
RESOURCES = {"taskPrice": ESCROW, "cpu": 1, "memory": 1, "storage": 40,
             "bandwidth": 1, "duration": 1, "validators": 1}
BALANCE_WEI = Web3.to_wei(751, "ether")
# A dropped RPC request, carrying the message the bug report quotes.
DROPPED = RequestsConnectionError("Failed to fetch")


def _rpc_error(message):
    """A Web3RPCError carrying the node's error.message."""
    return Web3RPCError(f"{{'code': -32000, 'message': '{message}'}}",
                        rpc_response={"jsonrpc": "2.0", "id": 1,
                                      "error": {"code": -32000, "message": message}})


def _answers(*outcomes):
    """A stand-in for a contract function's call(): the n-th call gets the
    n-th outcome, raised when it is an exception, returned otherwise. The
    stand-in's .calls lists the arguments of every call made."""
    pending = list(outcomes)
    calls = []

    def function(*args):
        calls.append(args)

        def call():
            outcome = pending.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return SimpleNamespace(call=call)

    function.calls = calls
    function.pending = pending
    return function


def _contract(balance_of, network_type="TESTNET"):
    """A BLOXBERG `network_type` protocolContract of the wallet WALLET whose
    token's balanceOf is the stand-in `balance_of`, with the faucet recorded
    in contract.calls instead of sent."""
    contract = protocolContract(SimpleNamespace(address=WALLET), "BLOXBERG", network_type)
    contract.token_contract = SimpleNamespace(functions=SimpleNamespace(balanceOf=balance_of))
    contract.calls = []
    contract.faucet = lambda: contract.calls.append(("faucet",))
    return contract


def _runner(monkeypatch, contract, allowance_of=None):
    """A runner of the contract's network holding `contract`, with the
    allowance read answered by the stand-in `allowance_of`, the approval and
    its wait recorded in contract.calls, and every sleep recorded in
    runner.sleeps instead of slept."""
    runner = EthernityCloudRunner("BLOXBERG", contract.network_config.__name__)
    runner.running = True
    runner.resources = RESOURCES
    runner.signer = contract.signer
    runner.contract = contract
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(allowance=allowance_of))

    def set_allowance(tokens):
        contract.calls.append(("approve", tokens))
        return TX

    def poll_transaction(tx_hash, max_attempts):
        contract.calls.append(("wait", tx_hash))
        return {"status": 1}

    contract.set_allowance = set_allowance
    runner.poll_transaction = poll_transaction
    runner.sleeps = []
    monkeypatch.setattr(runner_module.time, "sleep", runner.sleeps.append)
    return runner


def test_the_reads_are_tried_three_times_two_seconds_apart():
    assert PRE_REQUEST_READ_ATTEMPTS == 3
    assert PRE_REQUEST_READ_RETRY_SECONDS == 2


# protocolContract.get_balance

def test_a_balance_read_that_answers_gives_the_balance_in_tokens():
    balance_of = _answers(BALANCE_WEI)
    assert _contract(balance_of).get_balance() == 751
    assert balance_of.calls == [(WALLET,)]


def test_a_balance_read_the_provider_drops_raises_the_cause():
    with pytest.raises(RuntimeError) as failure:
        _contract(_answers(DROPPED)).get_balance()
    assert str(failure.value) == (
        f"could not read the tETNY balance of {WALLET} at {TESTNET_TOKEN}: Failed to fetch")
    assert failure.value.__cause__ is DROPPED


def test_a_balance_read_the_node_refuses_names_the_nodes_message():
    with pytest.raises(RuntimeError) as failure:
        _contract(_answers(_rpc_error("header not found"))).get_balance()
    assert str(failure.value) == (
        f"could not read the tETNY balance of {WALLET} at {TESTNET_TOKEN}: header not found")


def test_a_failed_balance_read_names_the_networks_token():
    with pytest.raises(RuntimeError) as failure:
        _contract(_answers(DROPPED), "MAINNET").get_balance()
    assert str(failure.value) == (
        f"could not read the ETNY balance of {WALLET} at {MAINNET_TOKEN}: Failed to fetch")


# EthernityCloudRunner._check_balance

def test_the_balance_check_raises_a_failed_reads_error_as_it_is(monkeypatch):
    errors = [DROPPED, _rpc_error("header not found"), RequestsConnectionError("connection reset")]
    runner = _runner(monkeypatch, _contract(_answers(*errors)))
    with pytest.raises(RuntimeError) as failure:
        runner._check_balance()
    assert str(failure.value) == (
        f"could not read the tETNY balance of {WALLET} at {TESTNET_TOKEN}: connection reset")
    assert failure.value.__cause__ is errors[2]


def test_a_failed_balance_read_draws_no_faucet(monkeypatch):
    runner = _runner(monkeypatch, _contract(_answers(DROPPED, DROPPED, DROPPED)))
    with pytest.raises(RuntimeError):
        runner._check_balance()
    assert runner.contract.calls == []


def test_a_failed_balance_read_on_the_mainnet_does_not_report_an_unfunded_wallet(monkeypatch):
    runner = _runner(monkeypatch, _contract(_answers(DROPPED, DROPPED, DROPPED), "MAINNET"))
    with pytest.raises(RuntimeError) as failure:
        runner._check_balance()
    assert "Insufficient" not in str(failure.value)
    assert runner.contract.calls == []


def test_a_balance_read_that_fails_twice_then_answers_passes(monkeypatch):
    balance_of = _answers(DROPPED, _rpc_error("header not found"), BALANCE_WEI)
    runner = _runner(monkeypatch, _contract(balance_of))
    runner._check_balance()
    assert balance_of.calls == [(WALLET,)] * 3
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS] * 2
    assert runner.contract.calls == []


def test_a_balance_read_that_fails_three_times_raises_the_last_error(monkeypatch):
    balance_of = _answers(RequestsConnectionError("first"), RequestsConnectionError("second"),
                          RequestsConnectionError("third"), BALANCE_WEI)
    runner = _runner(monkeypatch, _contract(balance_of))
    with pytest.raises(RuntimeError, match=": third$"):
        runner._check_balance()
    assert balance_of.calls == [(WALLET,)] * 3
    assert balance_of.pending == [BALANCE_WEI]
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS] * 2


def test_the_faucet_is_drawn_on_a_read_that_answered_an_empty_wallet(monkeypatch):
    runner = _runner(monkeypatch, _contract(_answers(DROPPED, DROPPED, 0)))
    runner._check_balance()
    assert runner.contract.calls == [("faucet",)]
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS] * 2


def test_an_unfunded_mainnet_wallet_is_reported_on_a_read_that_answered(monkeypatch):
    runner = _runner(monkeypatch, _contract(_answers(Web3.to_wei(ESCROW - 1, "ether")), "MAINNET"))
    with pytest.raises(ValueError, match="Insufficient wallet balance. Required: 5, Available: 4"):
        runner._check_balance()


def test_a_failed_balance_read_refuses_the_request_with_the_cause(monkeypatch):
    runner = _runner(monkeypatch, _contract(_answers(DROPPED, DROPPED, DROPPED)))
    runner._populate_event_queue()
    # The runner's run in progress, as run() makes it for its thread.
    run = runner_module._Run(runner.contract)
    runner._run = run
    runner._process_events("code", "", RESOURCES, run)
    assert runner.status == ECStatus.ERROR
    assert runner.last_error == (
        f"could not read the tETNY balance of {WALLET} at {TESTNET_TOKEN}: Failed to fetch")
    assert runner.processed_events == []
    assert runner.contract.calls == []


# EthernityCloudRunner.check_allowance

def test_an_allowance_read_that_fails_twice_then_answers_passes(monkeypatch):
    allowance_of = _answers(DROPPED, _rpc_error("header not found"), 0)
    runner = _runner(monkeypatch, _contract(_answers(BALANCE_WEI)), allowance_of)
    runner.check_allowance()
    assert allowance_of.calls == [(WALLET, TESTNET_PROTOCOL)] * 3
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS] * 2
    assert runner.contract.calls == [("approve", ESCROW), ("wait", TX)]


def test_an_allowance_read_that_fails_three_times_raises_the_cause(monkeypatch):
    allowance_of = _answers(DROPPED, DROPPED, _rpc_error("header not found"), 0)
    runner = _runner(monkeypatch, _contract(_answers(BALANCE_WEI)), allowance_of)
    with pytest.raises(RuntimeError) as failure:
        runner.check_allowance()
    assert str(failure.value) == (
        f"could not read the tETNY allowance of {WALLET} for {TESTNET_PROTOCOL} "
        f"at {TESTNET_TOKEN}: header not found")
    assert isinstance(failure.value.__cause__, Web3RPCError)
    assert allowance_of.pending == [0]
    assert runner.sleeps == [PRE_REQUEST_READ_RETRY_SECONDS] * 2
    assert runner.contract.calls == []


def test_the_approve_transaction_is_sent_once(monkeypatch):
    runner = _runner(monkeypatch, _contract(_answers(BALANCE_WEI)), _answers(0))
    sends = []

    def set_allowance(tokens):
        sends.append(tokens)
        raise Exception("Unable to send transaction: connection reset")

    runner.contract.set_allowance = set_allowance
    with pytest.raises(Exception, match="Unable to send transaction: connection reset"):
        runner.check_allowance()
    assert sends == [ESCROW]
    assert runner.sleeps == []
