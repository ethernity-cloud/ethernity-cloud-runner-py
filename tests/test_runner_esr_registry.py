"""The runner's free ESR reads (esr_version, esr_nonce) build their
ESRContract from the network name and type alone, so the registry address
comes from the esrAbi table through ESRContract.registry_address_for, and a
network without a table entry is refused."""
import pytest

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

WALLET = "0x" + "ab" * 20


class RecordingESR:
    calls = []

    def __init__(self, network_name, network_type, registry_address=None, request_kwargs=None):
        RecordingESR.calls.append((network_name, network_type, registry_address))

    def get_state(self, wallet, key):
        return {"cid": "Qm" + "a" * 44, "version": 3, "updated_at": 1, "valid": True}

    def get_nonce(self, wallet, key):
        return 5


@pytest.fixture
def amoy_runner(monkeypatch):
    monkeypatch.setattr(runner_module, "ESRContract", RecordingESR)
    RecordingESR.calls = []
    runner = EthernityCloudRunner("POLYGON", "AMOY")
    return runner


def test_esr_version_builds_the_contract_from_the_network_alone(amoy_runner):
    assert amoy_runner.esr_version("counter", enclave_wallet=WALLET) == {
        "wallet": WALLET, "version": 3, "cid": "Qm" + "a" * 44}
    assert RecordingESR.calls == [("POLYGON", "AMOY", None)]


def test_esr_nonce_builds_the_contract_from_the_network_alone(amoy_runner):
    assert amoy_runner.esr_nonce("counter", enclave_wallet=WALLET) == {"wallet": WALLET, "nonce": 5}
    assert RecordingESR.calls == [("POLYGON", "AMOY", None)]


def test_a_network_without_a_registry_refuses_the_free_read():
    runner = EthernityCloudRunner("POLYGON", "MAINNET")
    with pytest.raises(ValueError, match="POLYGON/MAINNET"):
        runner.esr_nonce("counter", enclave_wallet=WALLET)
