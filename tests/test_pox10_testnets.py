"""The testnet PoX 1.0 networks: BLOXBERG TESTNET_POX10 (bloxberg_testnet_pox10),
a copy of the bloxberg mainnet's PoX 1.0 contracts on chain 8995, and POLYGON
AMOY_POX10 (polygon_amoy_pox10), a copy of Polygon mainnet's on Amoy. Each is
used as its mainnet is: the bloxberg copy's PoX is its own token, so no
allowance is approved; the Amoy copy's PoX is apart from the tECLD token and
is approved for a request's escrow. The bloxberg copy's token has no faucet:
a wallet below a request's escrow is refused with the amount it lacks and no
transaction is sent; the Amoy copy's wallet draws the tECLD faucet while it
holds less than the 100 tokens below which that faucet gives, and is refused
the same way from there. Each network runs its two trustedzones and no other,
and they run on no other network. Neither is served by the bootnode's payload
intake, and the bloxberg copy reads the bloxberg testnet's Enclave State
Registry while the Amoy copy has none. No
chain: the contracts, the registry and the session are stand-ins, and the one
real protocolContract sends to a provider that keeps what it is sent."""
from pathlib import Path
from types import SimpleNamespace

import pytest
import rlp
from web3 import Web3

import ethernity_cloud_runner_py.runner as runner_module
import ethernity_cloud_runner_py.session as session_module
from ethernity_cloud_runner_py.contract.operation.esrContract import ESRContract
from ethernity_cloud_runner_py.contract.operation.protocolContract import protocolContract
from ethernity_cloud_runner_py.enums import ECEvent, ECNetwork, ECStatus, trustedzone_network
from ethernity_cloud_runner_py.errors import FeeCeilingError
from ethernity_cloud_runner_py.ipfs import INTAKE_NETWORKS
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

from test_fee_ceiling import GWEI, NONCE, SIGNER, THE_DEFAULT, TX, _Chain, _connect, _refusal

BLOXBERG_POX10 = ("BLOXBERG", "TESTNET_POX10")
AMOY_POX10 = ("POLYGON", "AMOY_POX10")
POX10_NETWORKS = pytest.mark.parametrize("network", [BLOXBERG_POX10, AMOY_POX10], ids=["bloxberg", "amoy"])

BLOXBERG_POX10_POX = "0x69A7bEB5Da2d3dA711d52E491D71e51296b08745"
BLOXBERG_POX10_REGISTRY = "0x7dBC1b591cc3b7136D863bc7430C6Db50E929665"
BLOXBERG_POX10_HEARTBEAT = "0x4426C87484038F9B720a6012A1191DA73bDa0ad3"
BLOXBERG_TESTNET_ESR = "0x0Ea1728EAE108FD3B9340ae91451348E2Cc6b4E4"
BLOXBERG_MAINNET_ESR = "0x4Bf5cDE3BFD73dd10B707f8B123Ba631D2EBEAD2"
AMOY_POX10_POX = "0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02"
AMOY_POX10_REGISTRY = "0xa2EE2a9118d0011AF05a6196c862D37d8c29F8eC"
AMOY_POX10_HEARTBEAT = "0x937F74419E31c1200e86B6D2439D9f12b3Fa12c9"
AMOY_TECLD = "0x9927809B61122B2af3f3b3A3303875e0687b8eE3"

WALLET = "0x" + "11" * 20
# Three instances over two hours at 5 tokens: an escrow of 30 tokens.
TERMED = {"taskPrice": 5, "validators": 3, "duration": 2}
TERMED_ESCROW = 30
RESOURCES = {"taskPrice": 1, "cpu": 1, "memory": 1, "storage": 1,
             "bandwidth": 1, "duration": 1, "validators": 1}
# The fields of an entry that name its contracts, its token, the token's faucet and its images.
OWN_FIELDS = {"IMAGE_REGISTRY_CONTRACT_ADDRESS", "PROTOCOL_ADDRESS", "TOKEN_ADDRESS", "HEARTBEAT_CONTRACT_ADDRESS",
              "TOKEN_NAME", "TOKEN_FAUCET", "TOKEN_FAUCET_BELOW", "INTEGRATION_TEST_IMAGE", "TRUSTEDZONE_IMAGE",
              "TRUSTEDZONES"}
BLOXBERG_POX10_ZONES = ("etny-pynithy-testnet-pox10", "etny-nodenithy-testnet-pox10")
AMOY_POX10_ZONES = ("ecld-pynithy-amoy-pox10", "ecld-nodenithy-amoy-pox10")
# The fields of an entry that are its chain's: the RPC, the chain id and the fees.
CHAIN_FIELDS = {"RPC_URL", "RPC_DELAY", "CHAIN_ID", "MIDDLEWARE", "BLOCK_TIME", "MINIMUM_GAS_AT_START",
                "GAS_PRICE_MEASURE", "EIP1559", "GAS_PRICE", "GAS_LIMIT", "MAX_FEE_PER_GAS",
                "MAX_PRIORITY_FEE_PER_GAS"}


def _unfunded(balance, missing):
    """The refusal of a BLOXBERG TESTNET_POX10 request of TERMED from WALLET, which holds `balance` tE10."""
    return (f"Insufficient wallet balance. Required: {TERMED_ESCROW}, Available: {balance}. The token tE10 "
            f"({BLOXBERG_POX10_POX}) of BLOXBERG TESTNET_POX10 has no faucet: the wallet {WALLET} needs a "
            f"transfer of {missing} tE10 or more before the request.")


def _fields(entry):
    return {name: getattr(entry, name) for name in dir(entry) if name.isupper()}


# ---- the entries ----

def test_the_bloxberg_copy_names_its_contracts_on_chain_8995():
    entry = ECNetwork.BLOXBERG.TESTNET_POX10
    assert entry.CHAIN_ID == 8995
    assert entry.RPC_URL == "https://bloxberg.ethernity.cloud"
    assert entry.PROTOCOL_ADDRESS == BLOXBERG_POX10_POX
    assert entry.TOKEN_ADDRESS == BLOXBERG_POX10_POX
    assert entry.IMAGE_REGISTRY_CONTRACT_ADDRESS == BLOXBERG_POX10_REGISTRY
    assert entry.HEARTBEAT_CONTRACT_ADDRESS == BLOXBERG_POX10_HEARTBEAT
    assert entry.TOKEN_NAME == "tE10"
    assert entry.TOKEN_FAUCET is False
    assert not hasattr(entry, "TOKEN_FAUCET_BELOW")
    assert entry.TRUSTEDZONE_IMAGE == entry.INTEGRATION_TEST_IMAGE == "etny-pynithy-testnet-pox10"
    assert entry.TRUSTEDZONES == BLOXBERG_POX10_ZONES


def test_the_amoy_copy_names_its_contracts_on_chain_80002():
    entry = ECNetwork.POLYGON.AMOY_POX10
    assert entry.CHAIN_ID == 80002
    assert entry.RPC_URL == "https://polygon-amoy-bor-rpc.publicnode.com"
    assert entry.PROTOCOL_ADDRESS == AMOY_POX10_POX
    assert entry.TOKEN_ADDRESS == AMOY_TECLD
    assert entry.IMAGE_REGISTRY_CONTRACT_ADDRESS == AMOY_POX10_REGISTRY
    assert entry.HEARTBEAT_CONTRACT_ADDRESS == AMOY_POX10_HEARTBEAT
    assert entry.TOKEN_NAME == "tECLD"
    assert not hasattr(entry, "TOKEN_FAUCET")
    assert entry.TOKEN_FAUCET_BELOW == 100
    assert entry.TRUSTEDZONE_IMAGE == entry.INTEGRATION_TEST_IMAGE == "ecld-pynithy-amoy-pox10"
    assert entry.TRUSTEDZONES == AMOY_POX10_ZONES


def test_the_bloxberg_copy_differs_from_the_bloxberg_mainnet_in_its_contracts_token_and_images_alone():
    copy, mainnet = _fields(ECNetwork.BLOXBERG.TESTNET_POX10), _fields(ECNetwork.BLOXBERG.MAINNET)
    assert {name for name in copy if copy[name] != mainnet.get(name)} == OWN_FIELDS - {"TOKEN_FAUCET_BELOW"}


def test_the_amoy_copy_holds_the_amoy_chain_and_token_and_polygon_mainnets_other_values():
    copy = _fields(ECNetwork.POLYGON.AMOY_POX10)
    amoy, mainnet = _fields(ECNetwork.POLYGON.AMOY), _fields(ECNetwork.POLYGON.MAINNET)
    assert set(amoy) == set(mainnet) | {"TOKEN_FAUCET_BELOW"}
    assert set(copy) == set(amoy) | {"TRUSTEDZONES"}
    for name in CHAIN_FIELDS | {"TOKEN_ADDRESS", "TOKEN_NAME", "TOKEN_FAUCET_BELOW"}:
        assert copy[name] == amoy[name], name
    for name in set(copy) - CHAIN_FIELDS - OWN_FIELDS:
        assert copy[name] == mainnet[name], name
    assert {name for name in copy if copy[name] != amoy.get(name)} == OWN_FIELDS - {
        "TOKEN_ADDRESS", "TOKEN_NAME", "TOKEN_FAUCET", "TOKEN_FAUCET_BELOW"}


def test_no_other_entry_names_a_contract_or_an_image_of_the_copies():
    own = {BLOXBERG_POX10_POX, BLOXBERG_POX10_REGISTRY, BLOXBERG_POX10_HEARTBEAT, AMOY_POX10_POX,
           AMOY_POX10_REGISTRY, AMOY_POX10_HEARTBEAT, "etny-pynithy-testnet-pox10", "ecld-pynithy-amoy-pox10"}
    for network_name, network in vars(ECNetwork).items():
        if network_name.startswith("_"):
            continue
        for type_name, entry in vars(network).items():
            if type_name.startswith("_") or (network_name, type_name) in (BLOXBERG_POX10, AMOY_POX10):
                continue
            assert not own & {value for value in _fields(entry).values() if isinstance(value, str)}, (
                f"{network_name} {type_name}")


# ---- the runner ----

@POX10_NETWORKS
def test_a_pox_1_0_testnet_is_neither_a_mainnet_type_nor_an_unsafe_network(network):
    runner = EthernityCloudRunner(*network)
    assert runner.is_mainnet() is False
    assert runner.is_unsafe() is False


def test_the_intake_keys_are_the_network_words():
    assert EthernityCloudRunner(*BLOXBERG_POX10)._intake_network() == "bloxberg_testnet_pox10"
    assert EthernityCloudRunner(*AMOY_POX10)._intake_network() == "polygon_amoy_pox10"


def test_set_network_moves_a_runner_to_a_pox_1_0_testnet(monkeypatch):
    """A runner connected on BLOXBERG TESTNET, whose PoX 2.0 is apart from
    its token: after set_network it holds the copy's PoX, which is its token,
    and sends there (test_set_network.py walks a whole run for every pair)."""
    chain = _Chain(8995, GWEI)
    runner = _connect(monkeypatch, EthernityCloudRunner("BLOXBERG", "TESTNET"), chain)
    assert runner.protocol_contract.address == "0x830c781F0352050343211B6BFA83600B3e77647C"
    assert runner.token_contract.address == "0x02882F03097fE8cD31afbdFbB5D72a498B41112c"
    runner.set_network("bloxberg", "testnet_pox10")
    assert (runner.network_name, runner.network_type) == BLOXBERG_POX10
    assert runner.network_config is ECNetwork.BLOXBERG.TESTNET_POX10
    assert runner.trustedZoneImage == "etny-pynithy-testnet-pox10"
    assert runner.contract.network_config is ECNetwork.BLOXBERG.TESTNET_POX10
    assert runner.protocol_contract.address == runner.token_contract.address == BLOXBERG_POX10_POX
    assert runner.contract.get_protocol_address() == runner.contract.get_token_address() == BLOXBERG_POX10_POX
    assert runner.escrow_needs_allowance() is False
    assert runner.contract.cancel_do_request(3) == TX
    [raw] = chain.sent
    assert Web3.to_checksum_address(rlp.decode(raw)[3]) == BLOXBERG_POX10_POX


@pytest.mark.parametrize("network, pynithy, nodenithy", [
    (BLOXBERG_POX10, "etny-pynithy-testnet-pox10", "etny-nodenithy-testnet-pox10"),
    (AMOY_POX10, "ecld-pynithy-amoy-pox10", "ecld-nodenithy-amoy-pox10"),
], ids=["bloxberg", "amoy"])
def test_a_task_runs_on_the_networks_trustedzone_or_the_one_it_names(network, pynithy, nodenithy):
    runner = EthernityCloudRunner(*network)
    assert runner._resolve_trustedzone(None) == pynithy
    assert runner._resolve_trustedzone(pynithy) == pynithy
    assert runner._resolve_trustedzone(nodenithy) == nodenithy


@POX10_NETWORKS
def test_a_pox_1_0_testnet_has_no_unsafe_network(network):
    runner = EthernityCloudRunner(*network)
    with pytest.raises(ValueError, match=f"{network[0]} {network[1]} has no -unsafe network"):
        runner._resolve_trustedzone("etny-pynithy-testnet-unsafe")


# ---- the trustedzones of a PoX 1.0 network run there and nowhere else ----

def _entries():
    """(network name, type name) of every entry of ECNetwork."""
    return [(network_name, type_name)
            for network_name, network in vars(ECNetwork).items() if not network_name.startswith("_")
            for type_name in vars(network) if not type_name.startswith("_")]


def _entry_of(network):
    return getattr(getattr(ECNetwork, network[0]), network[1])


def test_the_pox_1_0_networks_are_the_entries_that_name_their_trustedzones():
    named = {network: _entry_of(network).TRUSTEDZONES
             for network in _entries() if hasattr(_entry_of(network), "TRUSTEDZONES")}
    assert named == {BLOXBERG_POX10: BLOXBERG_POX10_ZONES, AMOY_POX10: AMOY_POX10_ZONES}
    for zone in BLOXBERG_POX10_ZONES:
        assert trustedzone_network(zone) == BLOXBERG_POX10
    for zone in AMOY_POX10_ZONES:
        assert trustedzone_network(zone) == AMOY_POX10
    for zone in ("etny-pynithy", "etny-pynithy-testnet", "ecld-pynithy-amoy", "etny-pynithy-testnet-pox10-unsafe"):
        assert trustedzone_network(zone) is None


@pytest.mark.parametrize("zone, home", [(zone, BLOXBERG_POX10) for zone in BLOXBERG_POX10_ZONES]
                         + [(zone, AMOY_POX10) for zone in AMOY_POX10_ZONES])
def test_a_pox_1_0_trustedzone_is_refused_on_every_other_network(zone, home):
    others = [network for network in _entries() if network != home]
    assert len(others) == 12
    for network in others:
        runner = EthernityCloudRunner(*network)
        with pytest.raises(ValueError) as refusal:
            runner._resolve_trustedzone(zone)
        assert str(refusal.value) == (
            f"{zone} is a trustedzone of the {home[0]} {home[1]} network and runs on no other: run it there, "
            f"not on {network[0]} {network[1]}"), network


@pytest.mark.parametrize("network, zones, zone", [
    (BLOXBERG_POX10, BLOXBERG_POX10_ZONES, "etny-pynithy"),
    (BLOXBERG_POX10, BLOXBERG_POX10_ZONES, "etny-pynithy-testnet"),
    (BLOXBERG_POX10, BLOXBERG_POX10_ZONES, "etny-nodenithy-testnet"),
    (BLOXBERG_POX10, BLOXBERG_POX10_ZONES, "my-own-trustedzone"),
    (AMOY_POX10, AMOY_POX10_ZONES, "ecld-pynithy"),
    (AMOY_POX10, AMOY_POX10_ZONES, "ecld-pynithy-amoy"),
    (AMOY_POX10, AMOY_POX10_ZONES, "ecld-nodenithy-amoy"),
])
def test_a_pox_1_0_network_runs_no_other_trustedzone(network, zones, zone):
    runner = EthernityCloudRunner(*network)
    with pytest.raises(ValueError) as refusal:
        runner._resolve_trustedzone(zone)
    assert str(refusal.value) == (
        f"{network[0]} {network[1]} runs only its trustedzones ({zones[0]}, {zones[1]}), and {zone} is not one "
        "of them")


def test_the_readme_gives_the_texts_of_the_two_trustedzone_refusals():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    for network, zone in ((("POLYGON", "AMOY"), "ecld-pynithy-amoy-pox10"), (AMOY_POX10, "ecld-pynithy-amoy")):
        with pytest.raises(ValueError) as refusal:
            EthernityCloudRunner(*network)._resolve_trustedzone(zone)
        assert str(refusal.value) in readme, zone


def test_the_other_pox_1_0_networks_trustedzone_is_refused_by_its_own_network():
    with pytest.raises(ValueError, match="is a trustedzone of the POLYGON AMOY_POX10 network and runs on no other"):
        EthernityCloudRunner(*BLOXBERG_POX10)._resolve_trustedzone("ecld-pynithy-amoy-pox10")


@pytest.mark.parametrize("submit", ["run", "run_session"])
@pytest.mark.parametrize("network, zone, message", [
    (("POLYGON", "AMOY"), "ecld-pynithy-amoy-pox10", "is a trustedzone of the POLYGON AMOY_POX10 network"),
    (("BLOXBERG", "MAINNET"), "etny-nodenithy-testnet-pox10", "is a trustedzone of the BLOXBERG TESTNET_POX10 network"),
    (AMOY_POX10, "ecld-pynithy-amoy", "POLYGON AMOY_POX10 runs only its trustedzones"),
    (BLOXBERG_POX10, "etny-pynithy", "BLOXBERG TESTNET_POX10 runs only its trustedzones"),
])
def test_a_trustedzone_of_the_wrong_generation_is_refused_before_any_read_or_transaction(monkeypatch, submit, network,
                                                                                        zone, message):
    chain = _Chain(_entry_of(network).CHAIN_ID, GWEI)
    runner = _connect(monkeypatch, EthernityCloudRunner(*network), chain)
    with pytest.raises(ValueError, match=message):
        getattr(runner, submit)(RESOURCES, "my-dapp-securelock", "v3", "code", trustedzone_enclave=zone)
    assert chain.requests == [] and chain.sent == []
    assert not runner.is_running()
    assert runner.task_thread is None


# ---- the storage ----

def test_the_bootnodes_intake_does_not_list_the_pox_1_0_testnets():
    assert "bloxberg_testnet_pox10" not in INTAKE_NETWORKS
    assert "polygon_amoy_pox10" not in INTAKE_NETWORKS


@POX10_NETWORKS
def test_a_run_without_storage_is_refused_before_any_transaction(network):
    runner = EthernityCloudRunner(*network)
    with pytest.raises(RuntimeError) as failure:
        runner.run(RESOURCES, "my-dapp-securelock", "v3", '___etny_result___("x")')
    message = str(failure.value)
    assert f"not {network[0]} {network[1]}" in message
    assert "set_storage_ipfs(url, token)" in message
    assert runner.ipfs_client is None
    assert not runner.is_running()
    assert runner.task_thread is None


@POX10_NETWORKS
def test_a_session_on_the_public_intake_is_refused_before_any_transaction(network):
    runner = EthernityCloudRunner(*network)
    runner.set_public_intake()
    with pytest.raises(RuntimeError, match=f"not {network[0]} {network[1]}"):
        runner.run_session(RESOURCES, "my-dapp-securelock", "v3", '___etny_result___("x")')
    assert not runner.is_running()


@POX10_NETWORKS
def test_a_runner_with_its_own_kubo_resolves_it(network):
    runner = EthernityCloudRunner(*network)
    runner.set_storage_ipfs("http://kubo:5001/api/v0", "writer-token")
    runner._resolve_storage()
    assert runner.storage().intake_url == ""
    assert runner.storage().headers == {"authorization": "writer-token"}


# ---- the Enclave State Registry ----

def test_the_bloxberg_copy_reads_the_bloxberg_testnets_registry():
    assert ESRContract.registry_address_for(*BLOXBERG_POX10) == BLOXBERG_TESTNET_ESR
    assert ESRContract(*BLOXBERG_POX10).contract.address == BLOXBERG_TESTNET_ESR
    assert ESRContract.registry_address_for("BLOXBERG", "MAINNET") == BLOXBERG_MAINNET_ESR


def test_the_amoy_copy_has_no_registry_as_polygon_mainnet_has_none():
    with pytest.raises(ValueError, match="POLYGON/AMOY_POX10"):
        ESRContract(*AMOY_POX10)
    with pytest.raises(ValueError, match="POLYGON/AMOY_POX10"):
        EthernityCloudRunner(*AMOY_POX10).esr_nonce("counter", enclave_wallet=WALLET)


# ---- the balance, the faucet and the allowance ----

def _stubbed_runner(monkeypatch, network, balance, allowance=0, resources=TERMED):
    """A `network` runner whose wallet WALLET holds `balance` tokens and an
    allowance of `allowance` wei for the PoX on the token, with the submission
    steps around the balance and allowance checks stubbed. runner.calls
    records, in order, the faucet draws ("faucet",), the allowance reads
    ("allowance", owner, spender), the approvals ("approve", tokens) and the
    waits for their receipt ("wait", tx)."""
    runner = EthernityCloudRunner(*network)
    runner.running = True
    runner.resources = resources
    runner.signer = SimpleNamespace(address=WALLET)
    runner.calls = []

    def set_allowance(tokens):
        runner.calls.append(("approve", tokens))
        return TX

    def allowance_of(owner, spender):
        runner.calls.append(("allowance", owner, spender))
        return SimpleNamespace(call=lambda: allowance)

    def poll_transaction(tx_hash, max_attempts):
        runner.calls.append(("wait", tx_hash))
        return {"status": 1}

    runner.contract = SimpleNamespace(
        get_balance=lambda: balance,
        get_orders_count=lambda: 0,
        get_protocol_address=lambda: runner.network_config.PROTOCOL_ADDRESS,
        set_allowance=set_allowance,
        faucet=lambda: runner.calls.append(("faucet",)))
    runner.token_contract = SimpleNamespace(functions=SimpleNamespace(allowance=allowance_of))
    runner.check_web3_connection = lambda: True
    runner.get_enclave_details = lambda: True
    runner.create_task = lambda code: True
    runner.poll_transaction = poll_transaction
    monkeypatch.setattr(runner_module, "ImageRegistryContract", lambda *args: SimpleNamespace())
    return runner


def _init_step(runner):
    """Runs the INIT step of a run attempt."""
    runner.event_queue.put(ECEvent.INIT)
    runner._run_attempt("code", "", runner.resources)
    assert runner.processed_events == ["INIT"]
    return runner


def _session_submission(monkeypatch, runner):
    """Runs a session's submission up to the order's approval."""
    runner._resolve_storage = lambda: None

    def check_order_for_task():
        runner.order_id = 7
        return True

    runner.check_order_for_task = check_order_for_task
    runner.approve_task = lambda: True
    monkeypatch.setattr(session_module, "EthernityCloudSession",
                        lambda runner, order_id, challenge=None: SimpleNamespace(order_id=order_id))
    return runner.run_session(runner.resources, "securelock", "v3", "code")


def test_the_bloxberg_copys_token_has_no_faucet_and_the_amoy_copys_has_one():
    assert EthernityCloudRunner(*BLOXBERG_POX10).token_has_faucet() is False
    assert EthernityCloudRunner(*AMOY_POX10).token_has_faucet() is True


def test_an_unfunded_wallet_of_the_bloxberg_copy_is_refused_with_the_amount_it_lacks(monkeypatch):
    runner = _stubbed_runner(monkeypatch, BLOXBERG_POX10, balance=TERMED_ESCROW - 1)
    runner.event_queue.put(ECEvent.INIT)
    with pytest.raises(ValueError) as refusal:
        runner._run_attempt("code", "", TERMED)
    assert str(refusal.value) == _unfunded(29, 1) == (
        "Insufficient wallet balance. Required: 30, Available: 29. The token tE10 "
        "(0x69A7bEB5Da2d3dA711d52E491D71e51296b08745) of BLOXBERG TESTNET_POX10 has no faucet: the wallet "
        "0x1111111111111111111111111111111111111111 needs a transfer of 1 tE10 or more before the request.")
    # No faucet draw, no allowance read and no approval: nothing was sent.
    assert runner.calls == []
    assert runner.processed_events == []


def test_the_readme_gives_the_text_of_that_refusal():
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    assert _unfunded(29, 1) in readme


def test_an_empty_wallet_of_the_bloxberg_copy_lacks_the_whole_escrow(monkeypatch):
    runner = _stubbed_runner(monkeypatch, BLOXBERG_POX10, balance=0)
    with pytest.raises(ValueError) as refusal:
        runner._check_balance()
    assert str(refusal.value) == _unfunded(0, 30)
    assert runner.calls == []


def test_a_fraction_of_a_token_does_not_count_towards_the_escrow(monkeypatch):
    # get_balance gives the Decimal Web3.from_wei gives; the check compares whole tokens.
    runner = _stubbed_runner(monkeypatch, BLOXBERG_POX10, balance=Web3.from_wei(29_500000000000000000, "ether"))
    with pytest.raises(ValueError) as refusal:
        runner._check_balance()
    assert str(refusal.value) == _unfunded(29, 1)


def test_a_run_of_an_unfunded_wallet_of_the_bloxberg_copy_ends_with_the_refusal(monkeypatch):
    runner = _stubbed_runner(monkeypatch, BLOXBERG_POX10, balance=TERMED_ESCROW - 1)
    runner._populate_event_queue()
    # The runner's run in progress, as run() makes it for its thread.
    run = runner_module._Run(runner.contract)
    runner._run = run
    runner._process_events("code", "", TERMED, run)
    assert runner.status == ECStatus.ERROR
    assert runner.last_error == _unfunded(29, 1)
    assert runner.processed_events == []
    assert runner.calls == []
    assert runner.is_running() is False


def test_a_session_of_an_unfunded_wallet_of_the_bloxberg_copy_raises_the_refusal(monkeypatch):
    runner = _stubbed_runner(monkeypatch, BLOXBERG_POX10, balance=TERMED_ESCROW - 1)
    with pytest.raises(ValueError) as refusal:
        _session_submission(monkeypatch, runner)
    assert str(refusal.value) == _unfunded(29, 1)
    assert runner.calls == []
    assert runner.is_running() is False


def test_a_funded_wallet_of_the_bloxberg_copy_submits_without_a_faucet_draw_or_an_allowance(monkeypatch):
    runner = _init_step(_stubbed_runner(monkeypatch, BLOXBERG_POX10, balance=TERMED_ESCROW))
    assert runner.escrow_needs_allowance() is False
    assert runner.calls == []


def test_a_funded_session_of_the_bloxberg_copy_reads_no_allowance(monkeypatch):
    runner = _stubbed_runner(monkeypatch, BLOXBERG_POX10, balance=TERMED_ESCROW)
    assert _session_submission(monkeypatch, runner).order_id == 7
    assert runner.calls == []


def test_an_unfunded_wallet_of_the_amoy_copy_draws_the_faucet_then_approves_its_pox(monkeypatch):
    runner = _init_step(_stubbed_runner(monkeypatch, AMOY_POX10, balance=TERMED_ESCROW - 1))
    assert runner.calls == [("faucet",), ("allowance", WALLET, AMOY_POX10_POX),
                            ("approve", TERMED_ESCROW), ("wait", TX)]


def test_a_funded_wallet_of_the_amoy_copy_draws_no_faucet(monkeypatch):
    runner = _init_step(_stubbed_runner(monkeypatch, AMOY_POX10, balance=TERMED_ESCROW))
    assert runner.calls == [("allowance", WALLET, AMOY_POX10_POX), ("approve", TERMED_ESCROW), ("wait", TX)]


# Three instances for an hour at 50 tokens: an escrow of 150 tokens, above the
# 100 tokens below which the tECLD faucet gives.
LARGE = {"taskPrice": 50, "validators": 3, "duration": 1}
LARGE_ESCROW = 150


def _faucet_does_not_give(balance, missing):
    """The refusal of a POLYGON AMOY_POX10 request of LARGE from WALLET, which holds `balance` tECLD."""
    return (f"Insufficient wallet balance. Required: {LARGE_ESCROW}, Available: {balance}. The token tECLD "
            f"({AMOY_TECLD}) of POLYGON AMOY_POX10 has a faucet that gives to a wallet holding less than 100 "
            f"tECLD: the wallet {WALLET} needs a transfer of {missing} tECLD or more before the request.")


@pytest.mark.parametrize("balance", [0, 99, Web3.from_wei(99_900000000000000000, "ether")],
                         ids=["empty", "99", "99.9"])
def test_a_wallet_of_the_amoy_copy_below_100_tokens_draws_the_faucet(monkeypatch, balance):
    runner = _init_step(_stubbed_runner(monkeypatch, AMOY_POX10, balance=balance, resources=LARGE))
    assert runner.calls == [("faucet",), ("allowance", WALLET, AMOY_POX10_POX),
                            ("approve", LARGE_ESCROW), ("wait", TX)]


@pytest.mark.parametrize("balance, missing", [(100, 50), (120, 30), (149, 1)])
def test_a_wallet_of_the_amoy_copy_from_100_tokens_below_the_escrow_is_refused_without_a_faucet_draw(
        monkeypatch, balance, missing):
    runner = _stubbed_runner(monkeypatch, AMOY_POX10, balance=balance, resources=LARGE)
    runner.event_queue.put(ECEvent.INIT)
    with pytest.raises(ValueError) as refusal:
        runner._run_attempt("code", "", LARGE)
    assert str(refusal.value) == _faucet_does_not_give(balance, missing)
    # No faucet draw, no allowance read and no approval: nothing was sent.
    assert runner.calls == []
    assert runner.processed_events == []


def test_that_refusal_names_the_token_the_rule_and_the_amount():
    assert _faucet_does_not_give(120, 30) == (
        "Insufficient wallet balance. Required: 150, Available: 120. The token tECLD "
        "(0x9927809B61122B2af3f3b3A3303875e0687b8eE3) of POLYGON AMOY_POX10 has a faucet that gives to a wallet "
        "holding less than 100 tECLD: the wallet 0x1111111111111111111111111111111111111111 needs a transfer of "
        "30 tECLD or more before the request.")


def test_a_session_of_such_a_wallet_of_the_amoy_copy_raises_the_refusal(monkeypatch):
    runner = _stubbed_runner(monkeypatch, AMOY_POX10, balance=120, resources=LARGE)
    with pytest.raises(ValueError) as refusal:
        _session_submission(monkeypatch, runner)
    assert str(refusal.value) == _faucet_does_not_give(120, 30)
    assert runner.calls == []
    assert runner.is_running() is False


AMOY_NETWORKS = pytest.mark.parametrize("network", [("POLYGON", "AMOY"), ("POLYGON", "AMOY_UNSAFE")],
                                        ids=["POLYGON AMOY", "POLYGON AMOY_UNSAFE"])


@AMOY_NETWORKS
@pytest.mark.parametrize("balance", [0, 99], ids=["empty", "99"])
def test_a_wallet_of_the_amoy_pox_2_0_networks_below_100_tokens_draws_the_faucet(monkeypatch, network, balance):
    """The PoX 2.0 networks of Polygon Amoy share the copy's tECLD, whose faucet gives below 100 tokens."""
    runner = _init_step(_stubbed_runner(monkeypatch, network, balance=balance, resources=LARGE))
    assert runner.calls == [("faucet",), ("allowance", WALLET, ECNetwork.POLYGON.AMOY.PROTOCOL_ADDRESS),
                            ("approve", LARGE_ESCROW), ("wait", TX)]


@AMOY_NETWORKS
@pytest.mark.parametrize("balance, missing", [(100, 50), (120, 30), (149, 1)])
def test_a_wallet_of_the_amoy_pox_2_0_networks_from_100_tokens_below_the_escrow_is_refused_without_a_faucet_draw(
        monkeypatch, network, balance, missing):
    runner = _stubbed_runner(monkeypatch, network, balance=balance, resources=LARGE)
    runner.event_queue.put(ECEvent.INIT)
    with pytest.raises(ValueError) as refusal:
        runner._run_attempt("code", "", runner.resources)
    assert str(refusal.value) == _faucet_does_not_give(balance, missing).replace(
        "POLYGON AMOY_POX10", f"POLYGON {network[1]}")
    assert runner.calls == []


def test_an_allowance_of_the_amoy_copy_at_the_escrow_is_left_as_it_is(monkeypatch):
    runner = _init_step(_stubbed_runner(monkeypatch, AMOY_POX10, balance=TERMED_ESCROW,
                                        allowance=Web3.to_wei(TERMED_ESCROW, "ether")))
    assert runner.calls == [("allowance", WALLET, AMOY_POX10_POX)]


def test_a_session_of_the_amoy_copy_walks_the_same_steps(monkeypatch):
    runner = _stubbed_runner(monkeypatch, AMOY_POX10, balance=TERMED_ESCROW - 1)
    assert _session_submission(monkeypatch, runner).order_id == 7
    assert runner.calls == [("faucet",), ("allowance", WALLET, AMOY_POX10_POX),
                            ("approve", TERMED_ESCROW), ("wait", TX)]


# ---- the contracts a connected runner holds ----

def test_the_bloxberg_copys_protocol_contract_is_its_token_contract():
    contract = protocolContract(SIGNER, *BLOXBERG_POX10)
    assert contract.chain_id == 8995
    assert contract.protocol_contract.address == contract.token_contract.address == BLOXBERG_POX10_POX
    assert contract.get_protocol_address() == contract.get_token_address() == BLOXBERG_POX10_POX


def test_the_amoy_copys_faucet_draw_is_a_type_2_transaction_to_the_tecld_token(monkeypatch):
    monkeypatch.delenv("ECLD_MAX_FEE_PER_GAS", raising=False)
    contract = protocolContract(SIGNER, *AMOY_POX10)
    assert contract.protocol_contract.address == AMOY_POX10_POX
    assert contract.token_contract.address == AMOY_TECLD
    # A base fee of 425 gwei: a fee of 499.5 gwei, within the network's ceiling of 500.
    chain = _Chain(80002, 425 * GWEI)
    contract.provider.provider = chain
    assert contract.faucet() == TX
    [raw] = chain.sent
    assert raw[0] == 2
    chain_id, nonce, priority_fee, max_fee, _gas, to, value, data = rlp.decode(raw[1:])[:8]
    assert (int.from_bytes(chain_id, "big"), int.from_bytes(nonce, "big")) == (80002, NONCE)
    assert int.from_bytes(priority_fee, "big") == 32 * GWEI
    assert int.from_bytes(max_fee, "big") == 499_500_000_000
    assert Web3.to_checksum_address(to) == AMOY_TECLD
    assert value == b""
    assert data == bytes(Web3.keccak(text="faucet()")[:4])


def test_the_amoy_copys_faucet_draw_is_refused_above_its_ceiling_of_500_gwei(monkeypatch):
    monkeypatch.delenv("ECLD_MAX_FEE_PER_GAS", raising=False)
    contract = protocolContract(SIGNER, *AMOY_POX10)
    # A base fee of 426 gwei: a fee of 500.6 gwei.
    chain = _Chain(80002, 426 * GWEI)
    contract.provider.provider = chain
    with pytest.raises(FeeCeilingError) as refused:
        contract.faucet()
    assert str(refused.value) == _refusal("426", "500.6", "500", THE_DEFAULT)
    assert chain.sent == []
