"""ESRContract reads the network's own Enclave State Registry: the esrAbi
table names Polygon Amoy and Amoy-unsafe, and a network the table does not
name is refused instead of being read on bloxberg's registry."""
import pytest

from ethernity_cloud_runner_py.contract.abi.esrAbi import contract as esr_abi
from ethernity_cloud_runner_py.contract.operation.esrContract import ESRContract

AMOY_ESR = "0x1DC58496ed1cA66FD1E0b51fA28A9E7451970843"


def test_the_table_names_amoy_and_amoy_unsafe():
    assert esr_abi["address_polygon_amoy"] == AMOY_ESR
    assert esr_abi["address_polygon_amoy_unsafe"] == AMOY_ESR


@pytest.mark.parametrize("network_type", ["AMOY", "AMOY_UNSAFE"])
def test_an_amoy_client_reads_the_amoy_registry(network_type):
    esr = ESRContract("POLYGON", network_type)
    assert esr.contract.address == AMOY_ESR


def test_every_unsafe_entry_shares_its_network_registry():
    for key, address in esr_abi.items():
        if key.endswith("_unsafe"):
            assert esr_abi[key[: -len("_unsafe")]] == address, key


def test_a_network_without_a_registry_is_refused():
    with pytest.raises(ValueError, match="POLYGON/MAINNET"):
        ESRContract("POLYGON", "MAINNET")
    with pytest.raises(ValueError):
        ESRContract.registry_address_for("IOTEX", "TESTNET")


def test_an_explicit_registry_address_is_used_as_given():
    given = "0x" + "ab" * 20
    esr = ESRContract("POLYGON", "MAINNET", registry_address=given)
    assert esr.contract.address.lower() == given


def test_the_bloxberg_registries_resolve_by_type_then_by_network():
    assert ESRContract.registry_address_for("BLOXBERG", "TESTNET") == esr_abi["address_bloxberg_testnet"]
    assert ESRContract.registry_address_for("BLOXBERG", "MAINNET") == esr_abi["address_bloxberg"]
