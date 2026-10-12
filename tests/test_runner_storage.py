"""EthernityCloudRunner: the storage client its uploads and reads go through.

The runner is constructed without a key or a connection; nothing here reaches
a chain or a storage endpoint."""
import pytest

from ethernity_cloud_runner_py import ipfs
from ethernity_cloud_runner_py.ipfs import IPFSClient, PUBLIC_INTAKE
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

RESOURCES = {"taskPrice": 1, "cpu": 1, "memory": 1, "storage": 1,
             "bandwidth": 1, "duration": 1, "validators": 1}


def test_intake_is_built_on_first_use():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    assert runner.ipfs_client is None
    client = runner.storage()
    assert isinstance(client, IPFSClient)
    assert client.intake_url == PUBLIC_INTAKE
    assert client.api_url == f"{PUBLIC_INTAKE}/api/v0"
    assert client.network == "bloxberg_testnet"
    assert client.headers == {}
    assert runner.storage() is client


def test_default_storage_queues_uploads_for_the_intake(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no request is made before the DO request exists")

    monkeypatch.setattr(ipfs.requests, "post", refuse)
    runner = EthernityCloudRunner()
    cid = runner.storage().upload_to_ipfs(b"challenge")
    assert runner.storage().pending == {cid: b"challenge"}


def test_set_network_rebuilds_the_intake_network_key():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.set_public_intake()
    runner.set_network("BLOXBERG", "TESTNET_UNSAFE")
    client = runner.storage()
    assert client.network == "bloxberg_testnet_unsafe"
    assert client.intake_url == PUBLIC_INTAKE


def test_set_network_rebuilds_the_default_intake():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    before = runner.storage()
    runner.set_network("POLYGON", "AMOY")
    after = runner.storage()
    assert after is not before
    assert after.network == "polygon_amoy"


def test_set_network_keeps_the_intake_base_url():
    runner = EthernityCloudRunner()
    runner.set_public_intake("https://intake.example/")
    runner.set_network("BLOXBERG", "MAINNET")
    client = runner.storage()
    assert client.intake_url == "https://intake.example"
    assert client.api_url == "https://intake.example/api/v0"
    assert client.network == "bloxberg_mainnet"


def test_set_network_leaves_an_own_kubo_client_alone():
    runner = EthernityCloudRunner()
    runner.set_storage_ipfs("http://kubo:5001/api/v0", "writer-token")
    own = runner.storage()
    runner.set_network("BLOXBERG", "MAINNET")
    assert runner.storage() is own
    assert own.intake_url == ""
    assert own.headers == {"authorization": "writer-token"}


def test_close_drops_the_storage_and_the_next_use_rebuilds_it():
    runner = EthernityCloudRunner()
    first = runner.storage()
    runner.close()
    assert runner.ipfs_client is None
    assert runner.storage() is not first


def test_mainnet_run_without_storage_is_refused_before_any_transaction():
    runner = EthernityCloudRunner("BLOXBERG", "MAINNET")
    with pytest.raises(RuntimeError) as failure:
        runner.run(RESOURCES, "my-dapp-securelock", "v3", '___etny_result___("x")')
    message = str(failure.value)
    assert "not BLOXBERG MAINNET" in message
    assert "set_storage_ipfs(url, token)" in message
    assert "writer token" in message
    assert runner.ipfs_client is None
    assert not runner.is_running()
    assert runner.task_thread is None


def test_mainnet_session_without_storage_is_refused_before_any_transaction():
    runner = EthernityCloudRunner("POLYGON", "MAINNET")
    with pytest.raises(RuntimeError, match="not POLYGON MAINNET"):
        runner.run_session(RESOURCES, "my-dapp-securelock", "v3", '___etny_result___("x")')
    assert runner.ipfs_client is None
    assert not runner.is_running()


def test_a_testnet_the_intake_does_not_serve_is_refused_before_any_transaction():
    runner = EthernityCloudRunner("POLYGON", "AMOY")
    with pytest.raises(RuntimeError, match="serves bloxberg_testnet, bloxberg_testnet_unsafe, not POLYGON AMOY"):
        runner.run(RESOURCES, "my-dapp-securelock", "v3", '___etny_result___("x")')
    assert runner.ipfs_client is None
    assert not runner.is_running()


def test_the_unsafe_bloxberg_testnet_resolves_the_default_intake():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET_UNSAFE")
    runner._resolve_storage()
    assert runner.ipfs_client.network == "bloxberg_testnet_unsafe"


def test_mainnet_runner_with_its_own_kubo_resolves_it():
    runner = EthernityCloudRunner("BLOXBERG", "MAINNET")
    runner.set_storage_ipfs("http://kubo:5001/api/v0", "writer-token")
    runner._resolve_storage()
    assert runner.storage().intake_url == ""
    assert runner.storage().headers == {"authorization": "writer-token"}


def test_an_explicit_public_intake_on_a_network_it_does_not_serve_is_refused_before_any_transaction():
    """ecld-run's default on LitVM: the intake has no route for the network,
    so the refusal comes before the DO request, not after it is on chain."""
    runner = EthernityCloudRunner("LITVM", "LITEFORGE")
    runner.set_public_intake()
    with pytest.raises(RuntimeError) as failure:
        runner.run(RESOURCES, "my-dapp-securelock", "v3", '___etny_result___("x")')
    message = str(failure.value)
    assert message.startswith("The bootnode's payload intake serves bloxberg_testnet, bloxberg_testnet_unsafe, not LITVM LITEFORGE")
    assert "set_storage_ipfs(url, token)" in message
    assert not runner.is_running()


def test_mainnet_runner_with_an_explicit_public_intake_is_refused():
    runner = EthernityCloudRunner("BLOXBERG", "MAINNET")
    runner.set_public_intake()
    with pytest.raises(RuntimeError, match="not BLOXBERG MAINNET"):
        runner._resolve_storage()


def test_an_intake_of_ones_own_serves_any_network():
    runner = EthernityCloudRunner("LITVM", "LITEFORGE")
    runner.set_public_intake("https://intake.example")
    runner._resolve_storage()
    assert runner.storage().network == "litvm_liteforge"
    assert runner.storage().intake_url == "https://intake.example"


def test_testnet_runner_resolves_the_default_intake():
    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner._resolve_storage()
    assert runner.ipfs_client.network == "bloxberg_testnet"


def test_mainnet_runner_reads_through_the_default_client():
    client = EthernityCloudRunner("BLOXBERG", "MAINNET").storage()
    assert client.api_url == f"{PUBLIC_INTAKE}/api/v0"
    assert client.headers == {}
