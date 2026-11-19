"""The node check of a run that names its node
(EthernityCloudRunner.is_node_operator_address): the protocol contract's
_getMyDPRequests read as a call from the node's address
(protocolContract.is_node_operator). An answer decides: a node with a DP
request passes, one with none is not a node operator. A read the contract or
the RPC refuses decides nothing about the node and raises RuntimeError with
what it is: a PoX its storage no longer lists as an allowed caller
(EthernityCloudStorage.allowedCallers, read through the implementation's
ethStorageAddress: protocolContract.storage_admission) as retired, with the
advice to upgrade the runner; any other failure with the contract's address
and the provider's message. No chain: the contracts and the provider are
stand-ins."""
from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from web3.exceptions import Web3RPCError

from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECNetwork
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

WALLET = "0x" + "11" * 20
NODE = "0x837EA0A09612CFF93a787db84Bbe11c65E431133"
POX = ECNetwork.BLOXBERG.TESTNET.PROTOCOL_ADDRESS
STORAGE = "0xEE3aAa1A7a8C00BeBBb5DfC570F80f6FA12a968d"
RETIRED = (f"The protocol contract {POX} is retired: its storage {STORAGE} no longer admits it, so every call "
           "through it is refused. Upgrade ethernity-cloud-runner-py: this version carries an address a later "
           "contract replaced.")


def _rpc_error(message):
    """A Web3RPCError carrying the node's error.message."""
    return Web3RPCError(f"{{'code': -32000, 'message': '{message}'}}",
                        rpc_response={"jsonrpc": "2.0", "id": 1,
                                      "error": {"code": -32000, "message": message}})


def _generic(reason):
    return (f"Could not verify the node address: the protocol contract {POX} did not answer the read of the "
            f"node's requests ({reason}).")


def _contract():
    """A BLOXBERG TESTNET protocolContract of the wallet WALLET; nothing is requested at construction."""
    return protocolContract(SimpleNamespace(address=WALLET), "BLOXBERG", "TESTNET")


def _requests_read(outcome, calls):
    """A protocol_contract whose _getMyDPRequests().call(tx) records tx and returns `outcome`, raised when it is an exception."""
    def call(tx):
        calls.append(tx)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return SimpleNamespace(functions=SimpleNamespace(_getMyDPRequests=lambda: SimpleNamespace(call=call)))


def _runner(is_node_operator, admission="unset"):
    """A BLOXBERG TESTNET runner whose contract answers is_node_operator with the given function and
    storage_admission with `admission`; runner.errors lists what it logged as errors."""
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.contract = SimpleNamespace(protocol_address=POX, is_node_operator=is_node_operator,
                                      storage_admission=lambda: admission)
    runner.errors = []
    runner.logger = SimpleNamespace(error=runner.errors.append, info=lambda *a: None, warning=lambda *a: None)
    return runner


def _raises(error):
    def is_node_operator(account):
        raise error
    return is_node_operator


def test_is_node_operator_reads_the_requests_from_the_nodes_address():
    contract = _contract()
    calls = []
    contract.protocol_contract = _requests_read([7], calls)
    assert contract.is_node_operator(NODE) is True
    contract.protocol_contract = _requests_read([], calls)
    assert contract.is_node_operator(NODE) is False
    assert calls == [{"from": NODE}, {"from": NODE}]


def test_is_node_operator_raises_what_the_read_raises():
    contract = _contract()
    refused = _rpc_error("execution reverted")
    contract.protocol_contract = _requests_read(refused, [])
    with pytest.raises(Web3RPCError) as raised:
        contract.is_node_operator(NODE)
    assert raised.value is refused


def test_storage_admission_asks_the_storage_the_implementation_names():
    contract = _contract()
    asked = []
    answers = {"admitted": False}

    def eth_contract(address, abi):
        name = abi[0]["name"]
        if name == "ethStorageAddress":
            return SimpleNamespace(functions=SimpleNamespace(
                ethStorageAddress=lambda: SimpleNamespace(call=lambda: asked.append((address, name)) or STORAGE)))
        return SimpleNamespace(functions=SimpleNamespace(
            allowedCallers=lambda who: SimpleNamespace(
                call=lambda: asked.append((address, name, who)) or answers["admitted"])))

    contract.provider = SimpleNamespace(eth=SimpleNamespace(contract=eth_contract))
    assert contract.storage_admission() == (STORAGE, False)
    answers["admitted"] = True
    assert contract.storage_admission() == (STORAGE, True)
    assert asked[:2] == [(POX, "ethStorageAddress"), (STORAGE, "allowedCallers", POX)]


def test_storage_admission_is_none_when_a_read_fails():
    contract = _contract()

    def no_pointer(address, abi):
        def call():
            raise _rpc_error("execution reverted")
        return SimpleNamespace(functions=SimpleNamespace(ethStorageAddress=lambda: SimpleNamespace(call=call)))

    contract.provider = SimpleNamespace(eth=SimpleNamespace(contract=no_pointer))
    assert contract.storage_admission() is None

    def no_allow_list(address, abi):
        if abi[0]["name"] == "ethStorageAddress":
            return SimpleNamespace(functions=SimpleNamespace(
                ethStorageAddress=lambda: SimpleNamespace(call=lambda: STORAGE)))

        def call():
            raise RequestsConnectionError("Failed to fetch")
        return SimpleNamespace(functions=SimpleNamespace(allowedCallers=lambda who: SimpleNamespace(call=call)))

    contract.provider = SimpleNamespace(eth=SimpleNamespace(contract=no_allow_list))
    assert contract.storage_admission() is None


def test_a_node_with_a_request_passes_and_one_without_is_not_a_node_operator():
    asked = []
    runner = _runner(lambda account: asked.append(account) or True)
    assert runner.is_node_operator_address(NODE) is True
    assert asked == [NODE]
    assert runner.errors == []
    none = _runner(lambda account: False)
    assert none.is_node_operator_address(NODE) is False
    assert none.errors == ["The target address is not a valid node operator address"]


def test_no_address_passes_without_a_read_and_a_string_that_is_no_address_does_not():
    runner = _runner(_raises(AssertionError("not to be called")))
    assert runner.is_node_operator_address("") is True
    assert runner.is_node_operator_address("0x1234") is False
    assert runner.errors == ["Introduced address is not a valid wallet address."]


def test_a_refused_read_on_a_pox_its_storage_no_longer_admits_is_a_retired_contract():
    runner = _runner(_raises(_rpc_error("execution reverted")), admission=(STORAGE, False))
    with pytest.raises(RuntimeError) as raised:
        runner.is_node_operator_address(NODE)
    assert str(raised.value) == RETIRED
    assert runner.errors == [RETIRED]
    assert "not a valid node operator" not in RETIRED


@pytest.mark.parametrize("admission", [(STORAGE, True), None])
def test_a_refused_read_otherwise_names_the_contract_and_the_providers_message(admission):
    runner = _runner(_raises(_rpc_error("execution reverted")), admission=admission)
    with pytest.raises(RuntimeError) as raised:
        runner.is_node_operator_address(NODE)
    assert str(raised.value) == _generic("execution reverted")
    assert runner.errors == [_generic("execution reverted")]
    dropped = _runner(_raises(RequestsConnectionError("Failed to fetch")), admission=admission)
    with pytest.raises(RuntimeError) as raised:
        dropped.is_node_operator_address(NODE)
    assert str(raised.value) == _generic("Failed to fetch")
