"""The ESR state cache keeps each network's entries under that network: the
Enclave State Registry of each network holds its own state for a wallet and
a key, so esr_read on one network serves no state cached on another, in a
runner moved with set_network and in a cache file two runners share. No
chain: the registry answers every free check alike on every network, and the
state-fetch task is a stand-in whose result carries the state of the network
the runner is on."""
import json

import pytest

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from ethernity_cloud_runner_py.state_cache import StateCache

AMOY = ("POLYGON", "AMOY")
AMOY_POX10 = ("POLYGON", "AMOY_POX10")
ENCLAVE_WALLET = "0x" + "5E" * 20
SECURELOCK = "my-dapp-securelock"
CID = "Qm" + "a" * 44
# The state each network's enclave holds under the key "counter".
STATES = {AMOY: {"network": "amoy"}, AMOY_POX10: {"network": "amoy pox 1.0"}}


class Registry:
    """Stands for ESRContract: every network's registry holds version 1 with CID for every wallet and key,
    which is what a free check finds current for an entry cached at version 1 with that CID."""

    def __init__(self, network_name, network_type):
        pass

    def get_state(self, wallet, key):
        return {"cid": CID, "version": 1, "updated_at": 1, "valid": True}


@pytest.fixture
def tasks(monkeypatch):
    """The networks the state-fetch tasks ran on, in order."""
    monkeypatch.setattr(runner_module, "ESRContract", Registry)
    return []


def _runner(network, tasks):
    """A `network` runner whose run() is the state-fetch task: its result is an envelope carrying the state
    of the network the runner is on, at version 1 with CID."""
    runner = EthernityCloudRunner(*network)

    def run(resources, enclave, version, code, **kwargs):
        on = (runner.network_name, runner.network_type)
        tasks.append(on)
        envelope = {"ecld": 1, "type": "json", "data": None, "esr": {"wallet": ENCLAVE_WALLET, "entries": [
            {"key": "counter", "state": STATES[on], "version": 1, "cid": CID}]}}
        runner.result = runner._apply_envelope({"success": True, "value": json.dumps(envelope)})

    runner.run = run
    return runner


def _read(runner):
    answer = runner.esr_read("counter", enclave_wallet=ENCLAVE_WALLET, securelock_enclave=SECURELOCK,
                             securelock_version="v3")
    return answer["state"], answer["from_cache"], answer["checked_on_chain"]


def test_a_state_cached_on_one_network_is_not_served_on_the_network_set(tasks):
    runner = _runner(AMOY, tasks)
    assert _read(runner) == ({"network": "amoy"}, False, False)
    assert _read(runner) == ({"network": "amoy"}, True, True)
    assert tasks == [AMOY]
    runner.set_network(*AMOY_POX10)
    assert _read(runner) == ({"network": "amoy pox 1.0"}, False, False)
    assert tasks == [AMOY, AMOY_POX10]
    assert _read(runner) == ({"network": "amoy pox 1.0"}, True, True)
    # Each network's entry is kept: back on the first, its state is served without a task.
    runner.set_network(*AMOY)
    assert _read(runner) == ({"network": "amoy"}, True, True)
    assert tasks == [AMOY, AMOY_POX10]


def test_a_cache_file_two_runners_share_keeps_each_networks_state_apart(tasks, tmp_path):
    file = str(tmp_path / "state.json")
    first = _runner(AMOY, tasks)
    first.enable_state_cache(file=file)
    assert _read(first) == ({"network": "amoy"}, False, False)
    second = _runner(AMOY_POX10, tasks)
    second.enable_state_cache(file=file)
    assert _read(second) == ({"network": "amoy pox 1.0"}, False, False)
    assert tasks == [AMOY, AMOY_POX10]
    third = _runner(AMOY, tasks)
    third.enable_state_cache(file=file)
    assert _read(third) == ({"network": "amoy"}, True, True)
    assert tasks == [AMOY, AMOY_POX10]
    with open(file, encoding="utf-8") as stored:
        assert sorted(json.load(stored)) == [
            f"polygon_amoy_pox10|{ENCLAVE_WALLET.lower()}|counter", f"polygon_amoy|{ENCLAVE_WALLET.lower()}|counter"]


def test_the_runners_key_for_a_network_is_its_name_and_type_in_lower_case():
    assert EthernityCloudRunner(*AMOY_POX10)._state_network() == "polygon_amoy_pox10"
    assert EthernityCloudRunner("BLOXBERG", "TESTNET")._state_network() == "bloxberg_testnet"


def test_the_cache_finds_an_entry_under_the_network_it_was_set_under_alone():
    cache = StateCache()
    cache.set(ENCLAVE_WALLET, "counter", {"n": 1}, 1, CID, network="polygon_amoy")
    assert cache.get(ENCLAVE_WALLET, "counter", network="polygon_amoy")["state"] == {"n": 1}
    assert cache.get(ENCLAVE_WALLET.lower(), "counter", network="polygon_amoy")["network"] == "polygon_amoy"
    assert cache.get(ENCLAVE_WALLET, "counter", network="polygon_amoy_pox10") is None
    assert cache.get(ENCLAVE_WALLET, "counter") is None
    cache.invalidate(ENCLAVE_WALLET, "counter", network="polygon_amoy_pox10")
    assert cache.get(ENCLAVE_WALLET, "counter", network="polygon_amoy") is not None
    cache.invalidate(ENCLAVE_WALLET, "counter", network="polygon_amoy")
    assert cache.get(ENCLAVE_WALLET, "counter", network="polygon_amoy") is None


def test_an_entry_set_without_a_network_is_kept_under_the_wallet_and_the_key():
    backend = {}
    cache = StateCache(backend=backend)
    cache.set(ENCLAVE_WALLET, "counter", {"n": 3}, 3, CID)
    assert list(backend) == [f"{ENCLAVE_WALLET.lower()}|counter"]
    assert "network" not in backend[f"{ENCLAVE_WALLET.lower()}|counter"]
    assert cache.get(ENCLAVE_WALLET, "counter")["version"] == 3
    assert cache.get(ENCLAVE_WALLET, "counter", network="polygon_amoy") is None
