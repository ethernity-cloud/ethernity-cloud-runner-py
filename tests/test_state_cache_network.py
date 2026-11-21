"""The ESR state cache keeps each network's entries under that network: the
Enclave State Registry of each network holds its own state for a wallet and
a key, so esr_read on one network serves no state cached on another, in a
runner moved with set_network and in a cache file two runners share. One
esr_read reads the network once: its cache key, its free check and its
state-fetch task are those of the network the call began on. An entry
ethernity-cloud-runner-py 0.5.38 wrote under the wallet and the key alone is
served when the network's registry holds its cid. No chain: the registry
answers every free check alike on every network, and the state-fetch task is
a stand-in whose result carries the state of the network the runner is on."""
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
    which is what a free check finds current for an entry cached at version 1 with that CID. BUILT lists the
    networks registries were built for, in order."""
    BUILT = []

    def __init__(self, network_name, network_type):
        Registry.BUILT.append((network_name, network_type))

    def get_state(self, wallet, key):
        return {"cid": CID, "version": 1, "updated_at": 1, "valid": True}


@pytest.fixture
def tasks(monkeypatch):
    """The networks the state-fetch tasks ran on, in order."""
    monkeypatch.setattr(runner_module, "ESRContract", Registry)
    monkeypatch.setattr(Registry, "BUILT", [])
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


# ---- the network of one esr_read ----

class MovingBackend(dict):
    """A cache backend whose first get() is the moment another thread moves `runner` to AMOY_POX10."""

    def __init__(self, runner):
        super().__init__()
        self.runner = runner
        self.moved = False

    def get(self, k, default=None):
        if not self.moved:
            self.moved = True
            self.runner.set_network(*AMOY_POX10)
        return super().get(k, default)


def test_esr_read_checks_the_entry_of_the_network_it_was_called_on_against_that_networks_registry(tasks):
    runner = _runner(AMOY, tasks)
    backend = MovingBackend(runner)
    cache = runner.enable_state_cache(backend=backend)
    cache.set(ENCLAVE_WALLET, "counter", STATES[AMOY], 1, CID, network="polygon_amoy")
    assert _read(runner) == ({"network": "amoy"}, True, True)
    assert backend.moved and (runner.network_name, runner.network_type) == AMOY_POX10
    assert Registry.BUILT == [AMOY]
    assert tasks == []


def test_esr_read_runs_no_state_fetch_task_on_a_network_the_runner_was_moved_to(tasks):
    """The entry of the network the read was called on is not current there (its CID differs from the
    registry's), and the runner is on another network when the task would be run: none is run."""
    runner = _runner(AMOY, tasks)
    cache = runner.enable_state_cache(backend=MovingBackend(runner))
    cache.set(ENCLAVE_WALLET, "counter", STATES[AMOY], 2, "Qm" + "b" * 44, network="polygon_amoy")
    with pytest.raises(RuntimeError) as refused:
        _read(runner)
    assert str(refused.value) == (
        "esr_read('counter') was called on POLYGON AMOY, and the runner was moved to POLYGON AMOY_POX10 before "
        "its state-fetch task: no task was run. Call esr_read again on the network meant.")
    assert Registry.BUILT == [AMOY]
    assert tasks == []


# ---- the entries ethernity-cloud-runner-py 0.5.38 wrote ----

LEGACY_KEY = f"{ENCLAVE_WALLET.lower()}|counter"


def _legacy(cid):
    """A backend holding what 0.5.38 cached for the key "counter": version 1 with `cid`, keyed by the wallet
    and the key."""
    return {LEGACY_KEY: {"state": {"network": "written by 0.5.38"}, "version": 1, "cid": cid,
                         "wallet": ENCLAVE_WALLET, "savedAt": 1}}


def test_an_entry_of_0_5_38_whose_cid_the_registry_holds_is_served_and_cached_under_the_network(tasks):
    runner = _runner(AMOY, tasks)
    backend = _legacy(CID)
    runner.enable_state_cache(backend=backend)
    assert _read(runner) == ({"network": "written by 0.5.38"}, True, True)
    assert tasks == []
    assert sorted(backend) == [LEGACY_KEY, f"polygon_amoy|{ENCLAVE_WALLET.lower()}|counter"]
    assert backend[f"polygon_amoy|{ENCLAVE_WALLET.lower()}|counter"]["cid"] == CID
    # The entry under the network's key serves the next read.
    del backend[LEGACY_KEY]
    assert _read(runner) == ({"network": "written by 0.5.38"}, True, True)
    assert tasks == []


def test_an_entry_of_0_5_38_in_a_cache_file_is_served(tasks, tmp_path):
    file = tmp_path / "state.json"
    file.write_text(json.dumps(_legacy(CID)), encoding="utf-8")
    runner = _runner(AMOY, tasks)
    runner.enable_state_cache(file=str(file))
    assert _read(runner) == ({"network": "written by 0.5.38"}, True, True)
    assert tasks == []
    assert sorted(json.loads(file.read_text(encoding="utf-8"))) == [
        LEGACY_KEY, f"polygon_amoy|{ENCLAVE_WALLET.lower()}|counter"]


@pytest.mark.parametrize("cid", ["", None, "Qm" + "b" * 44], ids=["empty", "none", "another"])
def test_an_entry_of_0_5_38_is_served_only_for_the_cid_the_registry_holds(tasks, cid):
    """Its version, 1, is the registry's: a version alone serves no entry of 0.5.38."""
    runner = _runner(AMOY, tasks)
    runner.enable_state_cache(backend=_legacy(cid))
    assert _read(runner) == ({"network": "amoy"}, False, cid is not None and cid != "")
    assert tasks == [AMOY]


def test_an_entry_of_the_network_is_read_before_an_entry_of_0_5_38(tasks):
    runner = _runner(AMOY, tasks)
    backend = _legacy(CID)
    cache = runner.enable_state_cache(backend=backend)
    cache.set(ENCLAVE_WALLET, "counter", STATES[AMOY], 1, CID, network="polygon_amoy")
    assert _read(runner) == ({"network": "amoy"}, True, True)


def test_an_entry_set_without_a_network_is_kept_under_the_wallet_and_the_key():
    backend = {}
    cache = StateCache(backend=backend)
    cache.set(ENCLAVE_WALLET, "counter", {"n": 3}, 3, CID)
    assert list(backend) == [f"{ENCLAVE_WALLET.lower()}|counter"]
    assert "network" not in backend[f"{ENCLAVE_WALLET.lower()}|counter"]
    assert cache.get(ENCLAVE_WALLET, "counter")["version"] == 3
    assert cache.get(ENCLAVE_WALLET, "counter", network="polygon_amoy") is None
