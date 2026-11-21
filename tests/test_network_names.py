"""The network table, held by value: every network name and type
EthernityCloudRunner takes, every field of every ECNetwork entry, the esrAbi
address table, ipfs.INTAKE_NETWORKS and what the runner derives from an entry
(its intake key, is_mainnet, is_unsafe, escrow_needs_allowance,
token_has_faucet, its default trustedzone and its Enclave State Registry). An
identifier or a value of a published network that changes fails here. No
chain: the runners are constructed without a key or a connection."""
import pytest

from ethernity_cloud_runner_py import ipfs
from ethernity_cloud_runner_py.contract.abi.esrAbi import contract as esr_abi
from ethernity_cloud_runner_py.contract.operation.esrContract import ESRContract
from ethernity_cloud_runner_py.enums import ECNetwork, UNSAFE_NETWORK_SUFFIX, UNSAFE_TRUSTEDZONE_SUFFIX
from ethernity_cloud_runner_py.runner import EthernityCloudRunner

# The network names and, under each, its types, in the order ECNetwork defines them.
NETWORKS = {
    "BLOXBERG": ["TESTNET", "TESTNET_UNSAFE", "MAINNET", "TESTNET_POX10"],
    "POLYGON": ["MAINNET", "AMOY", "AMOY_UNSAFE", "AMOY_POX10"],
    "IOTEX": ["TESTNET"],
    "ETHEREUM": ["SEPOLIA", "SEPOLIA_UNSAFE"],
    "LITVM": ["LITEFORGE", "LITEFORGE_UNSAFE"],
}

# The fields every entry holds with one value.
EVERY_ENTRY = {"TASK_EXECUTION_PRICE_DEFAULT": 1, "NETWORK_FEE": 5, "ENCLAVE_FEE": 10}
# Chain 8995, which sends at a fixed gas price, as the bloxberg entries hold it.
BLOXBERG_CHAIN = {
    "RPC_URL": "https://bloxberg.ethernity.cloud", "CHAIN_ID": 8995, "MIDDLEWARE": "POA", "BLOCK_TIME": 5,
    "MINIMUM_GAS_AT_START": 100000000000, "GAS_PRICE_MEASURE": "wei", "EIP1559": False,
    "GAS_PRICE": 2000000, "GAS_LIMIT": 2000000, "MAX_FEE_PER_GAS": 0, "MAX_PRIORITY_FEE_PER_GAS": 0,
    "REWARD_TYPE": 1,
}
# Chain 80002 as the Polygon Amoy entries hold it.
AMOY_CHAIN = {
    "RPC_URL": "https://polygon-amoy-bor-rpc.publicnode.com", "RPC_DELAY": 200, "CHAIN_ID": 80002,
    "MIDDLEWARE": "POA", "BLOCK_TIME": 2, "MINIMUM_GAS_AT_START": 100000000000000000,
    "GAS_PRICE_MEASURE": "gwei", "EIP1559": True, "GAS_PRICE": 0, "GAS_LIMIT": 0,
    "MAX_FEE_PER_GAS": 64, "MAX_PRIORITY_FEE_PER_GAS": 32, "REWARD_TYPE": 1,
}

BLOXBERG_TESTNET = {
    **EVERY_ENTRY, **BLOXBERG_CHAIN, "RPC_DELAY": 0,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0xa372a6e1Eb7Fcf343AF6b91E809b900C55001CD1",
    "PROTOCOL_ADDRESS": "0x830c781F0352050343211B6BFA83600B3e77647C",
    "TOKEN_ADDRESS": "0x02882F03097fE8cD31afbdFbB5D72a498B41112c",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x9B105aefF69Cd26050798d575db17ffc2eAC4E4d",
    "TOKEN_NAME": "tETNY",
    "INTEGRATION_TEST_IMAGE": "etny-pynithy-testnet",
    "TRUSTEDZONE_IMAGE": "etny-pynithy-testnet",
}
BLOXBERG_MAINNET = {
    **EVERY_ENTRY, **BLOXBERG_CHAIN, "RPC_DELAY": 200,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31",
    "PROTOCOL_ADDRESS": "0x549A6E06BB2084100148D50F51CF77a3436C3Ae7",
    "TOKEN_ADDRESS": "0x549A6E06BB2084100148D50F51CF77a3436C3Ae7",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x5c190f7253930C473822AcDED40B2eF1936B4075",
    "TOKEN_NAME": "ETNY",
    "INTEGRATION_TEST_IMAGE": "etny-pynithy",
    "TRUSTEDZONE_IMAGE": "etny-pynithy",
}
BLOXBERG_TESTNET_POX10 = {
    **EVERY_ENTRY, **BLOXBERG_CHAIN, "RPC_DELAY": 200,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0x7dBC1b591cc3b7136D863bc7430C6Db50E929665",
    "PROTOCOL_ADDRESS": "0x69A7bEB5Da2d3dA711d52E491D71e51296b08745",
    "TOKEN_ADDRESS": "0x69A7bEB5Da2d3dA711d52E491D71e51296b08745",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x4426C87484038F9B720a6012A1191DA73bDa0ad3",
    "TOKEN_NAME": "tE10",
    "TOKEN_FAUCET": False,
    "INTEGRATION_TEST_IMAGE": "etny-pynithy-testnet-pox10",
    "TRUSTEDZONE_IMAGE": "etny-pynithy-testnet-pox10",
}
POLYGON_MAINNET = {
    **EVERY_ENTRY,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0x689f3806874d3c8A973f419a4eB24e6fBA7E830F",
    "PROTOCOL_ADDRESS": "0x439945BE73fD86fcC172179021991E96Beff3Cc4",
    "TOKEN_ADDRESS": "0xc6920888988cAcEeA7ACCA0c96f2D65b05eE22Ba",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x2baddae93fdb8fae61a60587b789f27bf407406f",
    "TOKEN_NAME": "ECLD",
    "RPC_URL": "https://polygon-bor-rpc.publicnode.com", "RPC_DELAY": 10, "CHAIN_ID": 137,
    "MIDDLEWARE": "POA", "BLOCK_TIME": 2, "MINIMUM_GAS_AT_START": 100000000000000000,
    "GAS_PRICE_MEASURE": "gwei", "EIP1559": True, "GAS_PRICE": 0, "GAS_LIMIT": 0,
    "MAX_FEE_PER_GAS": 500, "MAX_PRIORITY_FEE_PER_GAS": 32, "REWARD_TYPE": 1,
    "INTEGRATION_TEST_IMAGE": "ecld-pynithy",
    "TRUSTEDZONE_IMAGE": "ecld-pynithy",
}
POLYGON_AMOY = {
    **EVERY_ENTRY, **AMOY_CHAIN,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0x0C0f52ebd72cd2d2cBe94F385c9e23cec528b706",
    "PROTOCOL_ADDRESS": "0xd1182deA61CDa785C320cdBE5888EaC4178cAAF2",
    "TOKEN_ADDRESS": "0x9927809B61122B2af3f3b3A3303875e0687b8eE3",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x2E27677fb67531eb09134fE331C27899f87ADe10",
    "TOKEN_NAME": "tECLD",
    "INTEGRATION_TEST_IMAGE": "ecld-pynithy-amoy",
    "TRUSTEDZONE_IMAGE": "ecld-pynithy-amoy",
}
POLYGON_AMOY_POX10 = {
    **EVERY_ENTRY, **AMOY_CHAIN,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0xa2EE2a9118d0011AF05a6196c862D37d8c29F8eC",
    "PROTOCOL_ADDRESS": "0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02",
    "TOKEN_ADDRESS": "0x9927809B61122B2af3f3b3A3303875e0687b8eE3",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x937F74419E31c1200e86B6D2439D9f12b3Fa12c9",
    "TOKEN_NAME": "tECLD",
    "INTEGRATION_TEST_IMAGE": "ecld-pynithy-amoy-pox10",
    "TRUSTEDZONE_IMAGE": "ecld-pynithy-amoy-pox10",
}
IOTEX_TESTNET = {
    **EVERY_ENTRY,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0xa7467A6391816be9367a1cC52E0ef0c15FfE3cCC",
    "PROTOCOL_ADDRESS": "0xD56385A97413Ed80E28B1b54A193b98F2C49c975",
    "TOKEN_ADDRESS": "0x95Aa17fCFaAB75e8ed7d7DF218045795dCeB9c50",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x379456B819f61eF775B0Fd80Cf1DbE47399eB6F7",
    "TOKEN_NAME": "tECLD",
    "RPC_URL": "https://babel-api.testnet.iotex.io", "RPC_DELAY": 200, "CHAIN_ID": 4690,
    "MIDDLEWARE": None, "BLOCK_TIME": 5, "MINIMUM_GAS_AT_START": 5000000000000000000,
    "GAS_PRICE_MEASURE": "gwei", "EIP1559": True, "GAS_PRICE": 0, "GAS_LIMIT": 0,
    "MAX_FEE_PER_GAS": 1500, "MAX_PRIORITY_FEE_PER_GAS": 1, "REWARD_TYPE": 2,
    "INTEGRATION_TEST_IMAGE": "ecld-pynithy-iotex-testnet",
    "TRUSTEDZONE_IMAGE": "ecld-pynithy-iotex-testnet",
}
ETHEREUM_SEPOLIA = {
    **EVERY_ENTRY,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0xa7E43a269E3307cf9d246b07df2B89CAA1b4C42F",
    "PROTOCOL_ADDRESS": "0x798975F9FdD90A21Cb11Ac26F1377e1542c58f9c",
    "TOKEN_ADDRESS": "0x2E27677fb67531eb09134fE331C27899f87ADe10",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x6D7F920958dfb9a13729723C1007b04eB7950E58",
    "TOKEN_NAME": "tECLD",
    "RPC_URL": "https://ethereum-sepolia-rpc.publicnode.com", "RPC_DELAY": 200, "CHAIN_ID": 11155111,
    "MIDDLEWARE": None, "BLOCK_TIME": 30, "MINIMUM_GAS_AT_START": 200000000000000000,
    "GAS_PRICE_MEASURE": "gwei", "EIP1559": True, "GAS_PRICE": 0, "GAS_LIMIT": 0,
    "MAX_FEE_PER_GAS": 15, "MAX_PRIORITY_FEE_PER_GAS": 1, "REWARD_TYPE": 2,
    "INTEGRATION_TEST_IMAGE": "ecld-pynithy-ethereum-sepolia",
    "TRUSTEDZONE_IMAGE": "ecld-pynithy-ethereum-sepolia",
}
LITVM_LITEFORGE = {
    **EVERY_ENTRY,
    "IMAGE_REGISTRY_CONTRACT_ADDRESS": "0xAf8Ce29103E1f59feDD49688ff070Ffc2346AF1D",
    "PROTOCOL_ADDRESS": "0xE35991de1f2A435e29E70406FA2781b1AffCb168",
    "TOKEN_ADDRESS": "0x95Aa17fCFaAB75e8ed7d7DF218045795dCeB9c50",
    "HEARTBEAT_CONTRACT_ADDRESS": "0x6D7F920958dfb9a13729723C1007b04eB7950E58",
    "TOKEN_NAME": "tECLD",
    "RPC_URL": "https://rpc.testnet.liteforge.zeeve.net/", "RPC_DELAY": 200, "CHAIN_ID": 4441,
    "MIDDLEWARE": None, "BLOCK_TIME": 1, "MINIMUM_GAS_AT_START": 200000000000000000,
    "GAS_PRICE_MEASURE": "gwei", "EIP1559": True, "GAS_PRICE": 0, "GAS_LIMIT": 0,
    "MAX_FEE_PER_GAS": 2, "MAX_PRIORITY_FEE_PER_GAS": 0, "REWARD_TYPE": 2,
    "INTEGRATION_TEST_IMAGE": "ecld-pynithy-litvm-testnet",
    "TRUSTEDZONE_IMAGE": "ecld-pynithy-litvm-testnet",
}


def _with_images(entry, image):
    """`entry` with `image` as its integration test image and its trustedzone."""
    return {**entry, "INTEGRATION_TEST_IMAGE": image, "TRUSTEDZONE_IMAGE": image}


# Every field of every entry.
TABLE = {
    ("BLOXBERG", "TESTNET"): BLOXBERG_TESTNET,
    ("BLOXBERG", "TESTNET_UNSAFE"): _with_images(BLOXBERG_TESTNET, "etny-pynithy-testnet-unsafe"),
    ("BLOXBERG", "MAINNET"): BLOXBERG_MAINNET,
    ("BLOXBERG", "TESTNET_POX10"): BLOXBERG_TESTNET_POX10,
    ("POLYGON", "MAINNET"): POLYGON_MAINNET,
    ("POLYGON", "AMOY"): POLYGON_AMOY,
    ("POLYGON", "AMOY_UNSAFE"): _with_images(POLYGON_AMOY, "ecld-pynithy-amoy-unsafe"),
    ("POLYGON", "AMOY_POX10"): POLYGON_AMOY_POX10,
    ("IOTEX", "TESTNET"): IOTEX_TESTNET,
    ("ETHEREUM", "SEPOLIA"): ETHEREUM_SEPOLIA,
    ("ETHEREUM", "SEPOLIA_UNSAFE"): _with_images(ETHEREUM_SEPOLIA, "ecld-pynithy-ethereum-sepolia-unsafe"),
    ("LITVM", "LITEFORGE"): LITVM_LITEFORGE,
    ("LITVM", "LITEFORGE_UNSAFE"): _with_images(LITVM_LITEFORGE, "ecld-pynithy-litvm-testnet-unsafe"),
}

BLOXBERG_ESR = "0x4Bf5cDE3BFD73dd10B707f8B123Ba631D2EBEAD2"
BLOXBERG_TESTNET_ESR = "0x0Ea1728EAE108FD3B9340ae91451348E2Cc6b4E4"
LITVM_ESR = "0x709052Fe77Af543d3d9FE2Ac06a15c635c8D4Be5"
SEPOLIA_ESR = "0x9927809B61122B2af3f3b3A3303875e0687b8eE3"
AMOY_ESR = "0x1DC58496ed1cA66FD1E0b51fA28A9E7451970843"
# The address entries of the esrAbi table.
ESR_TABLE = {
    "address_bloxberg": BLOXBERG_ESR,
    "address_bloxberg_testnet": BLOXBERG_TESTNET_ESR,
    "address_bloxberg_testnet_unsafe": BLOXBERG_TESTNET_ESR,
    "address_bloxberg_testnet_pox10": BLOXBERG_TESTNET_ESR,
    "address_litvm_liteforge": LITVM_ESR,
    "address_litvm_liteforge_unsafe": LITVM_ESR,
    "address_ethereum_sepolia": SEPOLIA_ESR,
    "address_ethereum_sepolia_unsafe": SEPOLIA_ESR,
    "address_polygon_amoy": AMOY_ESR,
    "address_polygon_amoy_unsafe": AMOY_ESR,
}

# The networks the bootnode's payload intake serves, by their intake key.
INTAKE_NETWORKS = ("bloxberg_testnet", "bloxberg_testnet_unsafe", "polygon_amoy", "polygon_amoy_unsafe",
                   "litvm_liteforge", "litvm_liteforge_unsafe", "ethereum_sepolia", "ethereum_sepolia_unsafe")

# What the runner derives from each entry: its intake key, is_mainnet(),
# is_unsafe(), escrow_needs_allowance(), token_has_faucet() and the Enclave
# State Registry its free ESR reads go to (None: the network has none).
DERIVED = {
    ("BLOXBERG", "TESTNET"): ("bloxberg_testnet", False, False, True, True, BLOXBERG_TESTNET_ESR),
    ("BLOXBERG", "TESTNET_UNSAFE"): ("bloxberg_testnet_unsafe", False, True, True, True, BLOXBERG_TESTNET_ESR),
    ("BLOXBERG", "MAINNET"): ("bloxberg_mainnet", True, False, False, False, BLOXBERG_ESR),
    ("BLOXBERG", "TESTNET_POX10"): ("bloxberg_testnet_pox10", False, False, False, False, BLOXBERG_TESTNET_ESR),
    ("POLYGON", "MAINNET"): ("polygon_mainnet", True, False, True, False, None),
    ("POLYGON", "AMOY"): ("polygon_amoy", False, False, True, True, AMOY_ESR),
    ("POLYGON", "AMOY_UNSAFE"): ("polygon_amoy_unsafe", False, True, True, True, AMOY_ESR),
    ("POLYGON", "AMOY_POX10"): ("polygon_amoy_pox10", False, False, True, True, None),
    ("IOTEX", "TESTNET"): ("iotex_testnet", False, False, True, True, None),
    ("ETHEREUM", "SEPOLIA"): ("ethereum_sepolia", False, False, True, True, SEPOLIA_ESR),
    ("ETHEREUM", "SEPOLIA_UNSAFE"): ("ethereum_sepolia_unsafe", False, True, True, True, SEPOLIA_ESR),
    ("LITVM", "LITEFORGE"): ("litvm_liteforge", False, False, True, True, LITVM_ESR),
    ("LITVM", "LITEFORGE_UNSAFE"): ("litvm_liteforge_unsafe", False, True, True, True, LITVM_ESR),
}

ENTRIES = pytest.mark.parametrize("network_name, network_type", list(TABLE),
                                  ids=[f"{name} {kind}" for name, kind in TABLE])


def _defined(holder):
    """The names `holder`'s class body defines, in its order, without the dunder ones."""
    return [name for name in vars(holder) if not name.startswith("_")]


def _fields(entry):
    """Every field of a table entry, those of the entry it extends included."""
    return {name: getattr(entry, name) for name in dir(entry) if name.isupper()}


def test_the_networks_and_their_types():
    assert _defined(ECNetwork) == list(NETWORKS)
    for network_name, types in NETWORKS.items():
        assert _defined(getattr(ECNetwork, network_name)) == types, network_name


def test_the_tables_of_this_file_name_the_same_entries():
    entries = [(network_name, kind) for network_name, types in NETWORKS.items() for kind in types]
    assert list(TABLE) == entries
    assert list(DERIVED) == entries


@ENTRIES
def test_every_field_of_the_entry(network_name, network_type):
    entry = getattr(getattr(ECNetwork, network_name), network_type)
    assert _fields(entry) == TABLE[(network_name, network_type)]


def test_the_bloxberg_testnet_pox_1_0_entry_is_the_one_that_holds_token_faucet():
    holding = [(network_name, kind) for network_name, kind in TABLE
               if hasattr(getattr(getattr(ECNetwork, network_name), kind), "TOKEN_FAUCET")]
    assert holding == [("BLOXBERG", "TESTNET_POX10")]
    assert ECNetwork.BLOXBERG.TESTNET_POX10.TOKEN_FAUCET is False


def test_the_esr_address_table():
    assert {key: value for key, value in esr_abi.items() if key != "abi"} == ESR_TABLE


def test_the_intake_networks():
    assert ipfs.INTAKE_NETWORKS == INTAKE_NETWORKS
    assert ipfs.PUBLIC_INTAKE == "https://ipfs.ethernity.cloud"


def test_the_unsafe_suffixes():
    assert UNSAFE_NETWORK_SUFFIX == "_UNSAFE"
    assert UNSAFE_TRUSTEDZONE_SUFFIX == "-unsafe"


@ENTRIES
def test_what_the_runner_derives_from_the_entry(network_name, network_type):
    intake_key, mainnet, unsafe, allowance, faucet, esr = DERIVED[(network_name, network_type)]
    runner = EthernityCloudRunner(network_name, network_type)
    assert (runner.network_name, runner.network_type) == (network_name, network_type)
    assert runner._intake_network() == intake_key
    assert runner.is_mainnet() is mainnet
    assert runner.is_unsafe() is unsafe
    assert runner.escrow_needs_allowance() is allowance
    assert runner.token_has_faucet() is faucet
    assert runner.trustedZoneImage == TABLE[(network_name, network_type)]["TRUSTEDZONE_IMAGE"]
    assert runner.block_time == TABLE[(network_name, network_type)]["BLOCK_TIME"]
    if esr is None:
        with pytest.raises(ValueError, match=f"{network_name}/{network_type}"):
            ESRContract.registry_address_for(network_name, network_type)
    else:
        assert ESRContract.registry_address_for(network_name, network_type) == esr


@ENTRIES
def test_the_names_are_taken_in_any_case(network_name, network_type):
    runner = EthernityCloudRunner(network_name.lower(), network_type.lower())
    assert (runner.network_name, runner.network_type) == (network_name, network_type)
    assert runner.network_config is getattr(getattr(ECNetwork, network_name), network_type)


def test_the_default_network_is_the_bloxberg_testnet():
    runner = EthernityCloudRunner()
    assert (runner.network_name, runner.network_type) == ("BLOXBERG", "TESTNET")


@pytest.mark.parametrize("network_name, network_type, message", [
    ("BLOXBERG", "AMOY_POX10", "Invalid network type: AMOY_POX10 for network BLOXBERG"),
    ("POLYGON", "TESTNET_POX10", "Invalid network type: TESTNET_POX10 for network POLYGON"),
    ("AMOY", "POX10", "Invalid network name: AMOY"),
])
def test_a_type_is_taken_under_its_own_network_only(network_name, network_type, message):
    with pytest.raises(ValueError, match=f"^{message}$"):
        EthernityCloudRunner(network_name, network_type)
