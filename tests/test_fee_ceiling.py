"""The fee ceiling of the runner's transactions. On a network whose table
entry says EIP1559, protocolContract offers for every send a maxFeePerGas of
int(baseFee * 1.1) plus the entry's priority fee and checks it against the
ceiling protocolContract.fee_ceiling resolves: the value given to
EthernityCloudRunner.set_max_fee_per_gas, before or after connect(); else the
environment variable ECLD_MAX_FEE_PER_GAS when it is set and not empty, read
at each send; else the entry's MAX_FEE_PER_GAS (500 gwei on Polygon mainnet).
A fee above the ceiling raises errors.FeeCeilingError before the transaction
is built, with the base fee, the fee computed, the ceiling and what set it; so
does a variable that is the ceiling in force and holds no positive whole
number of gwei, or one of more than 30 digits.
protocolContract._build_sign_send raises a refusal as it is,
and a DO request it refuses is not sent again
(EthernityCloudRunner.create_do_request), so a run refused at its faucet draw,
its token approval or its request ends at once with the refusal as its
last_error, while any other failure of a send is tried again. The approval of
an order is tried again after a refusal as after any failed send, under the
ceiling in force at each try. A network without EIP1559 sends at its fixed gas
price and reads none of the three. No chain: the contracts are real
protocolContract objects whose Web3 sends its requests to a provider that
answers the requests of a send and keeps the transactions it is sent; the key
is a throwaway one, and the steps of a submission around its sends, a
session's contract reads and the clock are stand-ins."""
import copy
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import rlp
from eth_account import Account
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout
from web3 import Web3
from web3.providers.base import BaseProvider

from ethernity_cloud_runner_py import errors as errors_module
from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECEvent, ECNetwork, ECStatus
from ethernity_cloud_runner_py.errors import FeeCeilingError
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from ethernity_cloud_runner_py.session import EthernityCloudSession

from test_session_wallet import Caller

VARIABLE = "ECLD_MAX_FEE_PER_GAS"
GWEI = 10 ** 9
KEY = "0x" + "11" * 32
SIGNER = Account.from_key(KEY)
POLYGON_MAINNET = ("POLYGON", "MAINNET")
POLYGON_AMOY = ("POLYGON", "AMOY")
BLOXBERG_TESTNET = ("BLOXBERG", "TESTNET")
# What the stand-in chain answers a send's requests with: the wallet's pending nonce, the gas estimate and the
# hash of the transaction it is sent.
NONCE = 7
ESTIMATE = 50_000
TX = "0x" + "ab" * 32
NODE = "0x" + "22" * 20
ORDER = 2022
RESOURCES = {"taskPrice": 1, "cpu": 1, "memory": 1, "storage": 40, "bandwidth": 1, "duration": 1, "validators": 1}
# The escrow of a request for RESOURCES, in wei: an allowance the allowance step leaves as it is.
ESCROW_WEI = Web3.to_wei(1, "ether")
# (EIP1559, MAX_FEE_PER_GAS, MAX_PRIORITY_FEE_PER_GAS) of every entry of ECNetwork.
FEE_TABLE = {
    ("BLOXBERG", "TESTNET"): (False, 0, 0),
    ("BLOXBERG", "TESTNET_UNSAFE"): (False, 0, 0),
    ("BLOXBERG", "MAINNET"): (False, 0, 0),
    ("BLOXBERG", "TESTNET_POX10"): (False, 0, 0),
    ("POLYGON", "MAINNET"): (True, 500, 32),
    ("POLYGON", "AMOY"): (True, 64, 32),
    ("POLYGON", "AMOY_UNSAFE"): (True, 64, 32),
    ("POLYGON", "AMOY_POX10"): (True, 64, 32),
    ("IOTEX", "TESTNET"): (True, 1500, 1),
    ("ETHEREUM", "SEPOLIA"): (True, 15, 1),
    ("ETHEREUM", "SEPOLIA_UNSAFE"): (True, 15, 1),
    ("LITVM", "LITEFORGE"): (True, 2, 0),
    ("LITVM", "LITEFORGE_UNSAFE"): (True, 2, 0),
}
# The highest base fee, in wei, whose maxFeePerGas is within Polygon mainnet's default: that fee is the ceiling.
HIGHEST_ADMITTED = 425_454_545_455
# What a send asks the chain, in order, when the ceiling refuses it and when it goes out; the second is also
# what one asks whose raw transaction the chain does not take. A network without EIP1559 reads no block.
REFUSED_SEND = ["eth_getTransactionCount", "eth_getBlockByNumber"]
SEND = REFUSED_SEND + ["eth_estimateGas", "eth_sendRawTransaction"]
LEGACY_SEND = ["eth_getTransactionCount", "eth_estimateGas", "eth_sendRawTransaction"]
# What set the ceiling, as a refusal names it.
THE_DEFAULT = "the network's default"
THE_SETTER = "set with set_max_fee_per_gas"
THE_VARIABLE = "set by the environment variable ECLD_MAX_FEE_PER_GAS"
# The refusal of a send at a base fee of 426 gwei on Polygon mainnet with nothing set, the text the README gives.
REFUSED_AT_426 = (
    "The network's base fee is 426 gwei; the maxFeePerGas computed for the transaction, 500.6 gwei (the base fee "
    "plus 10 %, plus the priority fee of 32 gwei), is above the fee ceiling of 500 gwei (the network's default), so "
    "the transaction was not sent. To send at this fee, raise the ceiling with "
    "EthernityCloudRunner.set_max_fee_per_gas(gwei) or, where that was not called, with the environment variable "
    "ECLD_MAX_FEE_PER_GAS (a whole number of gwei).")


@pytest.fixture(autouse=True)
def no_ceiling_in_the_environment(monkeypatch):
    """Every case starts without ECLD_MAX_FEE_PER_GAS, whatever the environment the suite runs in holds."""
    monkeypatch.delenv(VARIABLE, raising=False)


class _Chain(BaseProvider):
    """A provider answering the requests of a send on the chain `chain_id`: the wallet's pending nonce (NONCE),
    the latest block, whose base fee is the next of `base_fees` (wei) and the last of them from then on, the
    gas estimate (ESTIMATE) and the raw transaction, which it keeps in `sent` and answers with TX, or which it
    does not take, raising the next of `send_failures`, while one is left. `requests` lists the methods asked,
    in order, without the eth_chainId web3 asks of its own accord around a call."""

    def __init__(self, chain_id, *base_fees, send_failures=()):
        super().__init__()
        self.chain_id = chain_id
        self.base_fees = list(base_fees)
        self.send_failures = list(send_failures)
        self.requests = []
        self.sent = []

    def is_connected(self, show_traceback=False):
        return True

    def make_request(self, method, params):
        if method == "eth_chainId":
            return self._answer(hex(self.chain_id))
        self.requests.append(method)
        if method == "eth_getTransactionCount":
            return self._answer(hex(NONCE))
        if method == "eth_getBlockByNumber":
            base_fee = self.base_fees.pop(0) if len(self.base_fees) > 1 else self.base_fees[0]
            return self._answer({"number": "0x1", "baseFeePerGas": hex(base_fee)})
        if method == "eth_estimateGas":
            return self._answer(hex(ESTIMATE))
        if method == "eth_sendRawTransaction":
            if self.send_failures:
                raise self.send_failures.pop(0)
            self.sent.append(bytes.fromhex(params[0][2:]))
            return self._answer(TX)
        raise AssertionError(f"unexpected request {method}")

    @staticmethod
    def _answer(result):
        return {"jsonrpc": "2.0", "id": 1, "result": result}


# One protocolContract per network, built on first use: building one takes most of a second.
_BUILT = {}


def _contract(chain, network=POLYGON_MAINNET):
    """A protocolContract of `network` for the throwaway wallet whose Web3 sends its requests to `chain`. It is
    a copy of the network's entry in _BUILT: its attributes are its own and its Web3 is the entry's, so every
    contract of `network` this helper has given sends to the `chain` of its latest call."""
    if network not in _BUILT:
        _BUILT[network] = protocolContract(SIGNER, *network)
    _BUILT[network].provider.provider = chain
    return copy.copy(_BUILT[network])


def _connect(monkeypatch, runner, chain):
    """connect() of `runner`, with the throwaway key: the protocol contract it builds sends its requests to
    `chain`. Returns the runner."""
    class Offline(protocolContract):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.provider.provider = chain

    monkeypatch.setattr(runner_module, "protocolContract", Offline)
    runner.set_private_key(KEY)
    runner.connect()
    return runner


def _holding(chain):
    """A POLYGON MAINNET runner that holds a contract sending to `chain`, as connect() leaves it."""
    runner = EthernityCloudRunner(*POLYGON_MAINNET)
    runner.signer = SIGNER
    runner.contract = _contract(chain)
    return runner


def _fee(base_fee, priority_fee=32 * GWEI):
    """The maxFeePerGas offered at `base_fee`, in wei: 10 % over the base fee, plus the priority fee."""
    return int(base_fee * 1.1) + priority_fee


def _max_fee(raw):
    """The maxFeePerGas of a signed type-2 transaction."""
    assert raw[0] == 2
    return int.from_bytes(rlp.decode(raw[1:])[3], "big")


def _refusal(base_fee, fee, ceiling, source, priority_fee="32"):
    """The message of a refusal at `base_fee`, whose `fee` is above `ceiling`, set by `source`; the amounts
    are in gwei, as the message prints them."""
    return (f"The network's base fee is {base_fee} gwei; the maxFeePerGas computed for the transaction, {fee} gwei "
            f"(the base fee plus 10 %, plus the priority fee of {priority_fee} gwei), is above the fee ceiling of "
            f"{ceiling} gwei ({source}), so the transaction was not sent. To send at this fee, raise the ceiling "
            "with EthernityCloudRunner.set_max_fee_per_gas(gwei) or, where that was not called, with the "
            "environment variable ECLD_MAX_FEE_PER_GAS (a whole number of gwei).")


def _unusable(value):
    """The message of a send's refusal under a variable that holds `value`, no positive whole number of gwei."""
    return (f"The environment variable ECLD_MAX_FEE_PER_GAS is {value!r}, which is not a positive whole number of "
            "gwei, so the transaction was not sent. Set it to the fee ceiling in whole gwei, or unset it to send "
            "within the network's default.")


def _networks():
    """(network name, type name, table entry) for every entry of ECNetwork."""
    for network_name, network in vars(ECNetwork).items():
        if network_name.startswith("_"):
            continue
        for type_name, entry in vars(network).items():
            if not type_name.startswith("_"):
                yield network_name, type_name, entry


# ---- the table ----

def test_the_table_names_the_fee_ceiling_of_every_network():
    table = {(network_name, type_name): (entry.EIP1559, entry.MAX_FEE_PER_GAS, entry.MAX_PRIORITY_FEE_PER_GAS)
             for network_name, type_name, entry in _networks()}
    assert table == FEE_TABLE
    assert all(entry.GAS_PRICE_MEASURE == "gwei" for _, _, entry in _networks() if entry.EIP1559)


# ---- the network's default ----

def test_a_base_fee_of_425_gwei_is_sent_at_the_polygon_mainnet_default():
    chain = _Chain(137, 425 * GWEI)
    assert _contract(chain).set_allowance(1) == TX
    assert chain.requests == SEND
    [raw] = chain.sent
    assert raw[0] == 2
    chain_id, nonce, priority_fee, max_fee = (int.from_bytes(field, "big") for field in rlp.decode(raw[1:])[:4])
    assert (chain_id, nonce) == (137, NONCE)
    assert max_fee == int(425e9 * 1.1) + int(32e9) == 499_500_000_000
    assert priority_fee == 32 * GWEI


def test_a_base_fee_of_426_gwei_is_refused_at_the_polygon_mainnet_default(capsys):
    chain = _Chain(137, 426 * GWEI)
    with pytest.raises(FeeCeilingError) as refused:
        _contract(chain).set_allowance(1)
    assert str(refused.value) == REFUSED_AT_426 == _refusal("426", "500.6", "500", THE_DEFAULT)
    # The nonce and the latest block are read: no gas is estimated, nothing is signed or sent.
    assert chain.requests == REFUSED_SEND
    assert chain.sent == []
    # The refusal is printed once, as the failure of an attempt is.
    assert capsys.readouterr().out == f"Attempt 1: Exception encountered: {REFUSED_AT_426}\n"


def test_the_readme_gives_the_text_of_that_refusal():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    assert REFUSED_AT_426 in readme


def test_a_fee_at_the_ceiling_is_sent_and_one_a_wei_above_it_is_refused():
    assert _fee(HIGHEST_ADMITTED) == 500 * GWEI
    at_the_ceiling = _Chain(137, HIGHEST_ADMITTED)
    assert _contract(at_the_ceiling).set_allowance(1) == TX
    assert _max_fee(at_the_ceiling.sent[0]) == 500 * GWEI
    assert _fee(HIGHEST_ADMITTED + 1) == 500 * GWEI + 1
    above = _Chain(137, HIGHEST_ADMITTED + 1)
    with pytest.raises(FeeCeilingError) as refused:
        _contract(above).set_allowance(1)
    # The amounts are printed to the wei.
    assert str(refused.value) == _refusal("425.454545456", "500.000000001", "500", THE_DEFAULT)
    assert above.sent == []


@pytest.mark.parametrize("network, chain_id, priority_fee, sent_at, refused_at, refusal", [
    (POLYGON_AMOY, 80002, 32, 29, 30, _refusal("30", "65", "64", THE_DEFAULT)),
    (("IOTEX", "TESTNET"), 4690, 1, 1362, 1363, _refusal("1363", "1500.3", "1500", THE_DEFAULT, "1")),
    (("ETHEREUM", "SEPOLIA"), 11155111, 1, 12, 13, _refusal("13", "15.3", "15", THE_DEFAULT, "1")),
    (("LITVM", "LITEFORGE"), 4441, 0, 1, 2, _refusal("2", "2.2", "2", THE_DEFAULT, "0")),
], ids=["amoy", "iotex", "sepolia", "litvm"])
def test_the_default_of_every_other_eip1559_network_is_its_table_entry(network, chain_id, priority_fee, sent_at,
                                                                       refused_at, refusal):
    chain = _Chain(chain_id, sent_at * GWEI, refused_at * GWEI)
    contract = _contract(chain, network)
    assert contract.set_allowance(1) == TX
    assert _max_fee(chain.sent[0]) == _fee(sent_at * GWEI, priority_fee * GWEI)
    with pytest.raises(FeeCeilingError) as refused:
        contract.set_allowance(1)
    assert str(refused.value) == refusal
    assert len(chain.sent) == 1


# ---- EthernityCloudRunner.set_max_fee_per_gas ----

def test_a_ceiling_set_before_connect_is_the_ceiling_of_the_contract_connect_builds(monkeypatch):
    chain = _Chain(137, 430 * GWEI, 520 * GWEI)
    runner = EthernityCloudRunner(*POLYGON_MAINNET)
    runner.set_max_fee_per_gas(600)
    _connect(monkeypatch, runner, chain)
    # A fee of 505 gwei, above the network's 500.
    assert runner.contract.set_allowance(1) == TX
    assert _max_fee(chain.sent[0]) == _fee(430 * GWEI) == 505 * GWEI
    with pytest.raises(FeeCeilingError) as refused:
        runner.contract.set_allowance(1)
    assert str(refused.value) == _refusal("520", "604", "600", THE_SETTER)
    assert len(chain.sent) == 1


def test_a_ceiling_set_after_connect_is_the_ceiling_of_the_next_send(monkeypatch):
    chain = _Chain(137, 430 * GWEI)
    runner = _connect(monkeypatch, EthernityCloudRunner(*POLYGON_MAINNET), chain)
    with pytest.raises(FeeCeilingError) as refused:
        runner.contract.set_allowance(1)
    assert str(refused.value) == _refusal("430", "505", "500", THE_DEFAULT)
    runner.set_max_fee_per_gas(600)
    assert runner.contract.set_allowance(1) == TX
    assert _max_fee(chain.sent[0]) == 505 * GWEI
    runner.set_max_fee_per_gas(300)
    with pytest.raises(FeeCeilingError) as refused:
        runner.contract.set_allowance(1)
    assert str(refused.value) == _refusal("430", "505", "300", THE_SETTER)
    assert len(chain.sent) == 1


@pytest.mark.parametrize("value", [0, -1, 1.5, 500.0, "500", "abc", None, True, False], ids=repr)
def test_the_setter_refuses_what_is_no_positive_whole_number_of_gwei(value):
    message = f"The fee ceiling is a positive whole number of gwei, given as an int, not {value!r}."
    with pytest.raises(ValueError) as before_connect:
        EthernityCloudRunner(*POLYGON_MAINNET).set_max_fee_per_gas(value)
    assert str(before_connect.value) == message
    chain = _Chain(137, 430 * GWEI)
    runner = _holding(chain)
    runner.set_max_fee_per_gas(600)
    with pytest.raises(ValueError) as after_connect:
        runner.set_max_fee_per_gas(value)
    assert str(after_connect.value) == message
    # The ceiling given before stands: a fee of 505 gwei, above the network's 500, is sent.
    assert runner.contract.set_allowance(1) == TX


# ---- the environment variable ----

def test_the_environment_variable_is_the_ceiling_where_the_setter_gave_none(monkeypatch):
    monkeypatch.setenv(VARIABLE, "600")
    chain = _Chain(137, 430 * GWEI, 520 * GWEI)
    contract = _contract(chain)
    assert contract.set_allowance(1) == TX
    assert _max_fee(chain.sent[0]) == 505 * GWEI
    with pytest.raises(FeeCeilingError) as refused:
        contract.set_allowance(1)
    assert str(refused.value) == _refusal("520", "604", "600", THE_VARIABLE)
    assert len(chain.sent) == 1


def test_the_environment_variable_is_read_at_each_send(monkeypatch):
    chain = _Chain(137, 430 * GWEI)
    contract = _contract(chain)
    with pytest.raises(FeeCeilingError) as refused:
        contract.set_allowance(1)
    assert str(refused.value) == _refusal("430", "505", "500", THE_DEFAULT)
    monkeypatch.setenv(VARIABLE, "600")
    assert contract.set_allowance(1) == TX
    monkeypatch.setenv(VARIABLE, "504")
    with pytest.raises(FeeCeilingError) as refused:
        contract.set_allowance(1)
    assert str(refused.value) == _refusal("430", "505", "504", THE_VARIABLE)
    monkeypatch.delenv(VARIABLE)
    with pytest.raises(FeeCeilingError) as refused:
        contract.set_allowance(1)
    assert str(refused.value) == _refusal("430", "505", "500", THE_DEFAULT)
    assert len(chain.sent) == 1


def test_an_empty_environment_variable_leaves_the_networks_default(monkeypatch):
    monkeypatch.setenv(VARIABLE, "")
    chain = _Chain(137, 425 * GWEI, 426 * GWEI)
    contract = _contract(chain)
    assert contract.set_allowance(1) == TX
    with pytest.raises(FeeCeilingError) as refused:
        contract.set_allowance(1)
    assert str(refused.value) == REFUSED_AT_426


@pytest.mark.parametrize("value", ["abc", "0", "000", "-5", "+500", "1.5", "5e2", "0x1f4", "500 gwei", " 500",
                                   "500 ", "5_00", "\N{ARABIC-INDIC DIGIT FIVE}00"], ids=ascii)
def test_a_variable_that_holds_no_positive_whole_number_of_gwei_refuses_the_send(monkeypatch, value):
    monkeypatch.setenv(VARIABLE, value)
    # A base fee the network's default admits.
    chain = _Chain(137, 100 * GWEI)
    with pytest.raises(FeeCeilingError) as refused:
        _contract(chain).set_allowance(1)
    assert str(refused.value) == _unusable(value)
    # The latest block is not read.
    assert chain.requests == ["eth_getTransactionCount"]
    assert chain.sent == []


@pytest.mark.parametrize("digits", [31, 5000])
def test_a_variable_of_more_than_30_digits_refuses_the_send(monkeypatch, digits):
    # A number of 30 digits is the ceiling: a fee of 1,100,032 gwei, above the network's 500, is sent.
    monkeypatch.setenv(VARIABLE, "9" * 30)
    taken = _Chain(137, 10 ** 6 * GWEI)
    assert _contract(taken).set_allowance(1) == TX
    assert _max_fee(taken.sent[0]) == _fee(10 ** 6 * GWEI)
    # A longer one, at a base fee the network's default admits.
    value = "9" * digits
    monkeypatch.setenv(VARIABLE, value)
    chain = _Chain(137, 100 * GWEI)
    with pytest.raises(FeeCeilingError) as refused:
        _contract(chain).set_allowance(1)
    assert str(refused.value) == _unusable(value)
    # The latest block is not read.
    assert chain.requests == ["eth_getTransactionCount"]
    assert chain.sent == []


def test_a_runner_connects_under_a_variable_that_holds_no_ceiling_and_its_first_send_is_refused(monkeypatch):
    monkeypatch.setenv(VARIABLE, "abc")
    chain = _Chain(137, 100 * GWEI)
    runner = _connect(monkeypatch, EthernityCloudRunner(*POLYGON_MAINNET), chain)
    assert chain.requests == []
    with pytest.raises(FeeCeilingError) as refused:
        runner.contract.set_allowance(1)
    assert str(refused.value) == _unusable("abc")
    assert chain.sent == []


def test_the_variables_max_fee_per_gas_max_priority_fee_per_gas_and_gas_limit_are_not_read(monkeypatch):
    for name in ("MAX_FEE_PER_GAS", "MAX_PRIORITY_FEE_PER_GAS", "GAS_LIMIT"):
        monkeypatch.setenv(name, "1")
    chain = _Chain(137, 425 * GWEI, 426 * GWEI)
    contract = _contract(chain)
    assert contract.set_allowance(1) == TX
    [raw] = chain.sent
    # The network's priority fee, the fee of a base fee of 425 gwei and the gas floor of an approval.
    priority_fee, max_fee, gas = (int.from_bytes(field, "big") for field in rlp.decode(raw[1:])[2:5])
    assert (priority_fee, max_fee, gas) == (32 * GWEI, 499_500_000_000, 100_000)
    # A MAX_FEE_PER_GAS above the network's 500 gwei is no ceiling either.
    monkeypatch.setenv("MAX_FEE_PER_GAS", "1000")
    with pytest.raises(FeeCeilingError) as refused:
        contract.set_allowance(1)
    assert str(refused.value) == REFUSED_AT_426
    assert len(chain.sent) == 1


# ---- the order: the setter, the variable, the table ----

def test_the_setters_ceiling_is_taken_ahead_of_the_environment_variable(monkeypatch):
    monkeypatch.setenv(VARIABLE, "600")
    # A fee of 560 gwei: within the variable's 600, above the setter's 550.
    chain = _Chain(137, 480 * GWEI)
    runner = EthernityCloudRunner(*POLYGON_MAINNET)
    runner.set_max_fee_per_gas(550)
    _connect(monkeypatch, runner, chain)
    with pytest.raises(FeeCeilingError) as refused:
        runner.contract.set_allowance(1)
    assert str(refused.value) == _refusal("480", "560", "550", THE_SETTER)
    # Above the variable's 300, within the setter's 700.
    monkeypatch.setenv(VARIABLE, "300")
    runner.set_max_fee_per_gas(700)
    assert runner.contract.set_allowance(1) == TX
    assert _max_fee(chain.sent[0]) == 560 * GWEI


def test_the_environment_variable_is_taken_ahead_of_the_networks_default(monkeypatch):
    # A fee of 308.1 gwei, within the network's 500.
    chain = _Chain(137, 251 * GWEI)
    contract = _contract(chain)
    monkeypatch.setenv(VARIABLE, "308")
    with pytest.raises(FeeCeilingError) as refused:
        contract.set_allowance(1)
    assert str(refused.value) == _refusal("251", "308.1", "308", THE_VARIABLE)
    monkeypatch.setenv(VARIABLE, "309")
    assert contract.set_allowance(1) == TX
    assert _max_fee(chain.sent[0]) == 308_100_000_000


def test_a_variable_that_holds_no_ceiling_is_not_read_where_the_setter_gave_one(monkeypatch):
    monkeypatch.setenv(VARIABLE, "abc")
    chain = _Chain(137, 430 * GWEI)
    runner = EthernityCloudRunner(*POLYGON_MAINNET)
    runner.set_max_fee_per_gas(600)
    _connect(monkeypatch, runner, chain)
    assert runner.contract.set_allowance(1) == TX
    assert _max_fee(chain.sent[0]) == 505 * GWEI


def test_a_ceiling_above_every_amount_of_wei_a_transaction_holds_refuses_nothing():
    # 10**80 gwei is more than the 2**256 - 1 wei a fee field holds.
    chain = _Chain(137, 10 ** 6 * GWEI)
    runner = _holding(chain)
    runner.set_max_fee_per_gas(10 ** 80)
    assert runner.contract.set_allowance(1) == TX
    assert [_max_fee(raw) for raw in chain.sent] == [_fee(10 ** 6 * GWEI)]


# ---- a network without EIP1559 ----

def test_a_network_without_eip1559_sends_the_same_transaction_whatever_the_setter_and_the_variable(monkeypatch):
    plain = _Chain(8995)
    assert _contract(plain, BLOXBERG_TESTNET).set_allowance(1) == TX
    nonce, gas_price = (int.from_bytes(field, "big") for field in rlp.decode(plain.sent[0])[:2])
    assert (nonce, gas_price) == (NONCE, 2_000_000)
    # With a ceiling from the setter and one in the variable.
    monkeypatch.setenv(VARIABLE, "1")
    ruled = _Chain(8995)
    runner = EthernityCloudRunner(*BLOXBERG_TESTNET)
    runner.set_max_fee_per_gas(1)
    _connect(monkeypatch, runner, ruled)
    assert runner.contract.set_allowance(1) == TX
    # With a variable that holds no ceiling.
    monkeypatch.setenv(VARIABLE, "abc")
    unusable = _Chain(8995)
    assert _contract(unusable, BLOXBERG_TESTNET).set_allowance(1) == TX
    assert ruled.sent == unusable.sent == plain.sent
    assert ruled.requests == unusable.requests == plain.requests == LEGACY_SEND


def test_a_network_without_eip1559_sends_at_a_gas_price_above_the_setters_and_the_variables_ceiling(monkeypatch):
    # A gas price of 3 gwei, above the 2 gwei the setter gives and the 1 gwei the variable holds.
    monkeypatch.setattr(ECNetwork.BLOXBERG.TESTNET, "GAS_PRICE", 3 * GWEI)
    monkeypatch.setenv(VARIABLE, "1")
    by_variable = _Chain(8995)
    assert _contract(by_variable, BLOXBERG_TESTNET).set_allowance(1) == TX
    by_setter = _Chain(8995)
    runner = EthernityCloudRunner(*BLOXBERG_TESTNET)
    runner.set_max_fee_per_gas(2)
    _connect(monkeypatch, runner, by_setter)
    assert runner.contract.set_allowance(1) == TX
    for chain in (by_variable, by_setter):
        nonce, gas_price = (int.from_bytes(field, "big") for field in rlp.decode(chain.sent[0])[:2])
        assert (nonce, gas_price) == (NONCE, 3 * GWEI)
        assert chain.requests == LEGACY_SEND


# ---- the refusal ----

def test_the_refusal_is_an_exception_of_its_own_named_by_the_errors_module_and_the_runner_module():
    assert FeeCeilingError.__bases__ == (Exception,)
    assert "FeeCeilingError" in errors_module.__all__
    assert runner_module.FeeCeilingError is FeeCeilingError


@pytest.mark.parametrize("setter, variable, ceiling, source", [
    (None, None, "500", THE_DEFAULT),
    (None, "650", "650", THE_VARIABLE),
    (690, "650", "690", THE_SETTER),
], ids=["default", "variable", "setter"])
def test_the_refusal_states_the_base_fee_the_fee_computed_the_ceiling_and_what_set_it(monkeypatch, setter, variable,
                                                                                      ceiling, source):
    if variable is not None:
        monkeypatch.setenv(VARIABLE, variable)
    chain = _Chain(137, 600_250_000_000)
    runner = _holding(chain)
    if setter is not None:
        runner.set_max_fee_per_gas(setter)
    with pytest.raises(FeeCeilingError) as refused:
        runner.contract.set_allowance(1)
    assert str(refused.value) == (
        "The network's base fee is 600.25 gwei; the maxFeePerGas computed for the transaction, 692.275 gwei (the "
        f"base fee plus 10 %, plus the priority fee of 32 gwei), is above the fee ceiling of {ceiling} gwei "
        f"({source}), so the transaction was not sent. To send at this fee, raise the ceiling with "
        "EthernityCloudRunner.set_max_fee_per_gas(gwei) or, where that was not called, with the environment "
        "variable ECLD_MAX_FEE_PER_GAS (a whole number of gwei).")
    assert chain.sent == []


# The sends of the contract, by the name of their method.
SENDS = {
    "set_allowance": lambda contract: contract.set_allowance(1),
    "faucet": lambda contract: contract.faucet(),
    "add_do_request": lambda contract: contract.add_do_request("image", "code", "input", "", RESOURCES),
    "add_metadata_to_request": lambda contract: contract.add_metadata_to_request(7, "etny-si", "v1:0:9:cid:digest"),
    "approve_order": lambda contract: contract.approve_order(9),
    "cancel_do_request": lambda contract: contract.cancel_do_request(7),
}


@pytest.mark.parametrize("send", list(SENDS.values()), ids=list(SENDS))
def test_every_send_of_the_contract_is_checked_against_the_ceiling(send):
    chain = _Chain(137, 425 * GWEI, 426 * GWEI)
    contract = _contract(chain)
    assert send(contract) == TX
    assert _max_fee(chain.sent[0]) == 499_500_000_000
    with pytest.raises(FeeCeilingError) as refused:
        send(contract)
    assert str(refused.value) == REFUSED_AT_426
    assert len(chain.sent) == 1


# ---- a refused faucet draw, token approval or request is not tried again ----

def _submitting_runner(monkeypatch, chain, allowance=ESCROW_WEI, network=POLYGON_MAINNET, balance=100):
    """A runner of `network` whose protocol contract is a real one sending to `chain`, for the throwaway wallet,
    which holds `balance` tokens and `allowance` wei of allowance for the PoX. The reads of a submission and
    its steps other than the sends are stand-ins, and create_task is create_do_request with fixed metadata.
    runner.sends lists the contract's sends by the name of their method, in order, and runner.sleeps the
    sleeps asked for, none of them slept."""
    runner = EthernityCloudRunner(*network)
    runner.signer = SIGNER
    runner.resources = RESOURCES
    runner.sends, runner.sleeps = [], []
    contract = _contract(chain, network)

    def recorded(name):
        send = getattr(contract, name)

        def recording(*args):
            runner.sends.append(name)
            return send(*args)
        return recording

    for name in ("faucet", "set_allowance", "add_do_request", "approve_order", "cancel_do_request"):
        setattr(contract, name, recorded(name))
    contract.get_balance = lambda: balance
    contract.get_orders_count = lambda: 0
    runner.contract = contract
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(
        allowance=lambda owner, spender: SimpleNamespace(call=lambda: allowance)))
    runner.get_enclave_details = lambda: True
    runner.create_task = lambda code: runner.create_do_request("image", "code", "input", "")
    runner._resolve_storage = lambda: None
    monkeypatch.setattr(runner_module, "ImageRegistryContract", lambda *args: SimpleNamespace())
    monkeypatch.setattr(runner_module.time, "sleep", runner.sleeps.append)
    return runner


def _run(runner):
    """A run to its end, run() and the task thread it starts; returns the state it ends in."""
    runner.run(RESOURCES, "securelock", "v3", "code")
    runner.task_thread.join(10)
    assert not runner.task_thread.is_alive()
    return runner.get_state()


def test_a_refused_request_is_sent_to_the_contract_once_and_no_wait_follows(monkeypatch):
    chain = _Chain(137, 426 * GWEI)
    runner = _submitting_runner(monkeypatch, chain)
    with pytest.raises(FeeCeilingError) as refused:
        runner.create_do_request("image", "code", "input", "")
    assert str(refused.value) == REFUSED_AT_426
    assert runner.sends == ["add_do_request"]
    assert runner.sleeps == []
    assert chain.requests == REFUSED_SEND


def test_a_request_whose_send_fails_otherwise_is_sent_again_and_ends_at_the_refusal(monkeypatch):
    # The chain does not take the first two raw transactions; the third send meets a base fee of 426 gwei.
    dropped = [RequestsConnectionError("connection reset"), RequestsConnectionError("connection reset")]
    chain = _Chain(137, 100 * GWEI, 100 * GWEI, 426 * GWEI, send_failures=dropped)
    runner = _submitting_runner(monkeypatch, chain)
    with pytest.raises(FeeCeilingError) as refused:
        runner.create_do_request("image", "code", "input", "")
    assert str(refused.value) == REFUSED_AT_426
    assert runner.sends == ["add_do_request"] * 3
    # The waits after the two failures: Polygon's block time, then twice that.
    assert runner.sleeps == [2, 4]
    assert chain.requests == SEND + SEND + REFUSED_SEND
    assert chain.sent == []


def test_a_send_that_timed_out_is_built_again_and_ends_at_the_refusal():
    chain = _Chain(137, 100 * GWEI, 426 * GWEI, send_failures=[Timeout("read timed out")])
    with pytest.raises(FeeCeilingError) as refused:
        _contract(chain).set_allowance(1)
    assert str(refused.value) == REFUSED_AT_426
    assert chain.requests == SEND + REFUSED_SEND
    assert chain.sent == []


def test_a_run_whose_request_is_refused_ends_at_once_with_the_refusal(monkeypatch):
    chain = _Chain(137, 426 * GWEI)
    runner = _submitting_runner(monkeypatch, chain)
    state = _run(runner)
    assert state["status"] == "ERROR"
    assert state["progress"] == "FINISHED"
    assert state["last_error"] == REFUSED_AT_426
    assert state["result"] is None
    assert state["processed_events"] == []
    assert state["remaining_events"] == ["CREATED", "ORDER_PLACED", "IN_PROGRESS", "FINISHED"]
    assert runner.is_running() is False
    assert runner.sends == ["add_do_request"]
    assert runner.sleeps == []
    assert chain.sent == []


def test_a_run_whose_allowance_approval_is_refused_ends_with_the_refusal(monkeypatch):
    chain = _Chain(137, 426 * GWEI)
    runner = _submitting_runner(monkeypatch, chain, allowance=0)
    state = _run(runner)
    assert (state["status"], state["progress"]) == ("ERROR", "FINISHED")
    assert state["last_error"] == REFUSED_AT_426
    assert runner.is_running() is False
    # The request is not reached.
    assert runner.sends == ["set_allowance"]
    assert runner.sleeps == []
    assert chain.sent == []


def test_a_run_whose_faucet_draw_is_refused_ends_with_the_refusal(monkeypatch):
    # Polygon Amoy, whose ceiling is 64 gwei: a fee of 65.
    chain = _Chain(80002, 30 * GWEI)
    runner = _submitting_runner(monkeypatch, chain, network=POLYGON_AMOY, balance=0)
    state = _run(runner)
    assert (state["status"], state["progress"]) == ("ERROR", "FINISHED")
    assert state["last_error"] == _refusal("30", "65", "64", THE_DEFAULT)
    assert runner.sends == ["faucet"]
    assert runner.sleeps == []
    assert chain.sent == []


# ---- the approval of an order and the cancel of a request ----

def test_an_order_approval_refused_at_every_try_is_tried_fifty_times_and_ends_the_run_with_the_refusal(monkeypatch):
    chain = _Chain(137, 426 * GWEI)
    runner = _submitting_runner(monkeypatch, chain)
    runner.running = True
    runner.order_id = 9
    runner.event_queue.put(ECEvent.ORDER_PLACED)
    runner._process_events("code", "", RESOURCES)
    assert (runner.status, runner.progress) == (ECStatus.ERROR, ECEvent.FINISHED)
    assert runner.last_error == REFUSED_AT_426
    assert runner.running is False
    assert runner.sends == ["approve_order"] * 50
    # The waits between the tries: Polygon's block time, doubled up to a minute.
    assert runner.sleeps == [2, 4, 8, 16, 32] + [60] * 44
    assert chain.requests == REFUSED_SEND * 50
    assert chain.sent == []


def test_an_order_approval_goes_out_under_a_ceiling_raised_between_its_tries(monkeypatch):
    chain = _Chain(137, 426 * GWEI)
    runner = _submitting_runner(monkeypatch, chain)
    runner.running = True
    runner.order_id = 9
    runner.wait_for_transaction_to_be_processed = lambda contract, transaction_hash, max_attempts: True
    runner.contract.get_order = lambda order_id: (SIGNER.address, NODE)

    def wait(seconds):
        """The second wait is the moment the application raises the ceiling over the fee of 500.6 gwei."""
        runner.sleeps.append(seconds)
        if len(runner.sleeps) == 2:
            runner.set_max_fee_per_gas(501)

    monkeypatch.setattr(runner_module.time, "sleep", wait)
    assert runner.approve_order() is True
    assert runner.sends == ["approve_order"] * 3
    assert runner.sleeps == [2, 4]
    assert chain.requests == REFUSED_SEND * 2 + SEND
    assert _max_fee(chain.sent[0]) == _fee(426 * GWEI) == 500_600_000_000
    assert runner.node_address == NODE


def test_a_refused_cancel_is_logged_and_the_request_is_reported_as_one_no_node_took(monkeypatch):
    chain = _Chain(137, 426 * GWEI)
    runner = _submitting_runner(monkeypatch, chain)
    runner.do_request = 7
    runner.find_order = lambda do_request: False
    errors = []
    runner.logger = SimpleNamespace(error=errors.append, warning=lambda *a: None, info=lambda *a: None)
    assert runner.cancel_unclaimed_request(1800) is False
    assert errors == [f"Request 7 could not be cancelled: {REFUSED_AT_426}"]
    assert runner.sends == ["cancel_do_request"]
    assert runner.sleeps == []
    assert chain.sent == []


# ---- a session ----

def test_a_session_whose_request_is_refused_raises_the_refusal(monkeypatch):
    chain = _Chain(137, 426 * GWEI)
    runner = _submitting_runner(monkeypatch, chain)
    with pytest.raises(FeeCeilingError) as refused:
        runner.run_session(RESOURCES, "securelock", "v3", "code")
    assert str(refused.value) == REFUSED_AT_426
    assert runner.is_running() is False
    assert runner.sends == ["add_do_request"]
    assert runner.sleeps == []
    assert chain.sent == []


def _session(chain):
    """A session of order ORDER, PROCESSING within its hour, whose runner holds a real protocol contract
    sending to `chain`, seals an input as the CID "cid" and has a storage without an intake."""
    caller = Caller([])
    runner = SimpleNamespace(
        protocol_contract=SimpleNamespace(caller=lambda: caller),
        retry_operation=lambda read: read(),
        contract=_contract(chain),
        _seal_artefact=lambda plaintext: ("cid", "digest"),
        storage=lambda: SimpleNamespace(intake_url=""),
        private_key=KEY,
        logger=logging.getLogger("test"))
    return EthernityCloudSession(runner, ORDER)


def test_a_session_input_and_a_close_that_are_refused_are_raised_and_leave_the_session_as_it_was():
    chain = _Chain(137, 426 * GWEI)
    session = _session(chain)
    with pytest.raises(FeeCeilingError) as refused:
        session.send_input("hello")
    assert str(refused.value) == REFUSED_AT_426
    assert session.get_status()["inputs_sent"] == 0
    with pytest.raises(FeeCeilingError) as refused:
        session.close(wait=False)
    assert str(refused.value) == REFUSED_AT_426
    assert session.closed is False
    assert chain.requests == REFUSED_SEND * 2
    assert chain.sent == []
