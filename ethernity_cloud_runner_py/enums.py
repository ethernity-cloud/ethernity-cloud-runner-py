from enum import Enum
from enum import IntEnum

class ECStatus(Enum):
    ERROR: str = "Error"
    SUCCESS: str = "Success"
    RUNNING: str = "Running"


class ECEvent(Enum):
    INIT: str = "Task initialized"
    CREATED: str = "Task created"
    ORDER_PLACED: str = "Order placed"
    IN_PROGRESS: str = "In Progress"
    FINISHED: str = "Finished"


ECOrderTaskStatus = {
    0: "SUCCESS",
    1: "SYSTEM_ERROR",
    2: "KEY_ERROR",
    3: "SYNTAX_WARNING",
    4: "BASE_EXCEPTION",
    5: "PAYLOAD_NOT_DEFINED",
    6: "PAYLOAD_CHECKSUM_ERROR",
    7: "INPUT_CHECKSUM_ERROR",
    8: "EXECVE",
    # Extended diagnostics emitted by newer enclave builds (canonical registry:
    # the trustedzone TaskStatus enum in etny_exec.py). 20-36 and 38 are
    # customer-side outcomes; 37, 39 and 40 are node-side faults the validator
    # refunds, listed in OPERATOR_FAULT_CODES below.
    20: "SIGNATURE_ERROR",
    21: "SYNTAX_ERROR",
    22: "MEMORY_ERROR",
    23: "NAME_ERROR",
    24: "TYPE_ERROR",
    25: "VALUE_ERROR",
    26: "INDEX_ERROR",
    27: "ATTRIBUTE_ERROR",
    28: "IMPORT_ERROR",  # serverless backend failed to import inside the enclave
    29: "OS_ERROR",
    30: "ZERO_DIVISION_ERROR",
    31: "RUNTIME_ERROR",
    32: "CONFIG_ERROR",  # required enclave config value empty in the sealed image
    33: "EXECUTION_TIMEOUT",
    34: "ESR_GAS_LIMIT_EXCEEDED",  # ESR state commits would exceed the per-order relayed-gas budget
    35: "SECURITY_VIOLATION",      # a state commit was authorized under a caller other than the
    36: "ESR_NONCE_VIOLATION",     # a commit's idempotency nonce was already used -- duplicate
                                  # task submitter (the in-enclave ownership check was bypassed);
                                  # set by the securelock and/or the trustedzone re-adjudication
    37: "ESR_RELAY_TIMEOUT",       # signed state commits did not land on the registry in time
    38: "ESR_COMMIT_LIMIT_EXCEEDED",  # more than the per-run cap of state commits
    39: "SESSION_RELAY_FAULT",     # the node withheld session input delivery or failed to relay
    # The CAS that provisioned the enclave presented a quote the enclave could
    # not bind to its own injected environment; the enclave terminated the
    # order for refund. Set by the trustedzone (etny_exec.py TaskStatus) and by
    # the securelock alike. Codes 41-45 are not defined by any enclave and the
    # node emits no task codes of its own, so nothing on the network produces
    # them.
    40: "CAS_ATTESTATION_FAULT",
}

# Task codes attributed to the node operator rather than the submitted code:
# the node did not relay signed state commits (37), withheld session input or
# output rows (39), or was provisioned by a CAS whose self-attestation failed
# the ValidatorRegistry checks (40). The escrow for such orders is refunded by
# the validator, so resubmitting the same task as a new DO request is safe and
# is what the runner's retry does. 38 (per-run commit cap) is a dApp-side
# fault and is not refunded.
OPERATOR_FAULT_CODES = frozenset({37, 39, 40})


def task_status_name(code: int) -> str:
    """Name for a task code, tolerant of codes newer than this runner."""
    return ECOrderTaskStatus.get(code, f"UNKNOWN_{code}")


class ECOrderTaskStatusCode(Enum):
    SUCCESS = "SUCCESS"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    KEY_ERROR = "KEY_ERROR"
    SYNTAX_WARNING = "SYNTAX_WARNING"
    BASE_EXCEPTION = "BASE_EXCEPTION"
    PAYLOAD_NOT_DEFINED = "PAYLOAD_NOT_DEFINED"
    PAYLOAD_CHECKSUM_ERROR = "PAYLOAD_CHECKSUM_ERROR"
    INPUT_CHECKSUM_ERROR = "INPUT_CHECKSUM_ERROR"
    EXECVE = "EXECVE"

# An -unsafe network: a network type ending in _UNSAFE, with the chain and
# contracts of the type it is named after and the trustedzones that run without
# a CAS, whose names end in -unsafe. The runner runs an -unsafe trustedzone only
# on an -unsafe network, and no other trustedzone there.
UNSAFE_NETWORK_SUFFIX = "_UNSAFE"
UNSAFE_TRUSTEDZONE_SUFFIX = "-unsafe"


class ECNetwork:
    class BLOXBERG:

        class TESTNET:
            # ECImageRegistryV2, where the testnet trustedzones and the
            # securelocks published against them are registered.
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0x99A84C624C028bdf0a855A1E9E3f2fcf7275B3D8'
            PROTOCOL_ADDRESS='0x02882F03097fE8cD31afbdFbB5D72a498B41112c'
            TOKEN_ADDRESS='0x02882F03097fE8cD31afbdFbB5D72a498B41112c'
            HEARTBEAT_CONTRACT_ADDRESS='0x9B105aefF69Cd26050798d575db17ffc2eAC4E4d'
            TOKEN_NAME='tETNY'
            RPC_URL='https://bloxberg.ethernity.cloud'
            RPC_DELAY=0
            CHAIN_ID=8995
            MIDDLEWARE='POA'
            BLOCK_TIME=5
            MINIMUM_GAS_AT_START=100000000000
            GAS_PRICE_MEASURE='wei'
            EIP1559=False
            GAS_PRICE=2000000
            GAS_LIMIT=2000000
            MAX_FEE_PER_GAS=0
            MAX_PRIORITY_FEE_PER_GAS=0
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='etny-pynithy-testnet'
            TRUSTEDZONE_IMAGE='etny-pynithy-testnet'
            REWARD_TYPE=1
            NETWORK_FEE=5
            ENCLAVE_FEE=10

        class TESTNET_UNSAFE(TESTNET):
            # The chain and contracts of TESTNET, with the trustedzones that
            # run without a CAS (hardware SGX platforms the CAS cannot
            # attest): a task chosen to run unsafe names this network.
            INTEGRATION_TEST_IMAGE='etny-pynithy-testnet-unsafe'
            TRUSTEDZONE_IMAGE='etny-pynithy-testnet-unsafe'

        class MAINNET:
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31'
            PROTOCOL_ADDRESS='0x549A6E06BB2084100148D50F51CF77a3436C3Ae7'
            TOKEN_ADDRESS='0x549A6E06BB2084100148D50F51CF77a3436C3Ae7'
            HEARTBEAT_CONTRACT_ADDRESS='0x5c190f7253930C473822AcDED40B2eF1936B4075'
            TOKEN_NAME='ETNY'
            RPC_URL='https://bloxberg.ethernity.cloud'
            RPC_DELAY=200
            CHAIN_ID=8995
            MIDDLEWARE='POA'
            BLOCK_TIME=5
            MINIMUM_GAS_AT_START=100000000000
            GAS_PRICE_MEASURE='wei'
            EIP1559=False
            GAS_PRICE=2000000
            GAS_LIMIT=2000000
            MAX_FEE_PER_GAS=0
            MAX_PRIORITY_FEE_PER_GAS=0
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='etny-pynithy'
            TRUSTEDZONE_IMAGE='etny-pynithy'
            REWARD_TYPE=1
            NETWORK_FEE=5
            ENCLAVE_FEE=10

    class POLYGON:
        class MAINNET:
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0x689f3806874d3c8A973f419a4eB24e6fBA7E830F'
            PROTOCOL_ADDRESS='0x439945BE73fD86fcC172179021991E96Beff3Cc4'
            TOKEN_ADDRESS='0xc6920888988cAcEeA7ACCA0c96f2D65b05eE22Ba'
            HEARTBEAT_CONTRACT_ADDRESS='0x2baddae93fdb8fae61a60587b789f27bf407406f'
            TOKEN_NAME='ECLD'
            RPC_URL='https://polygon-bor-rpc.publicnode.com'
            RPC_DELAY=10
            CHAIN_ID=137
            MIDDLEWARE='POA'
            BLOCK_TIME=2
            MINIMUM_GAS_AT_START=100000000000000000
            GAS_PRICE_MEASURE='gwei'
            EIP1559=True
            GAS_PRICE=0
            GAS_LIMIT=0
            MAX_FEE_PER_GAS=200
            MAX_PRIORITY_FEE_PER_GAS=32
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='ecld-pynithy'
            TRUSTEDZONE_IMAGE='ecld-pynithy'
            REWARD_TYPE=1
            NETWORK_FEE=5
            ENCLAVE_FEE=10
        class AMOY:
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0xeFA33c3976f31961285Ae4f5D10188616C912728'
            PROTOCOL_ADDRESS='0x1579b37C5a69ae02dDd23263A2b1318DE66a27C3'
            TOKEN_ADDRESS='0x9927809B61122B2af3f3b3A3303875e0687b8eE3'
            HEARTBEAT_CONTRACT_ADDRESS='0x2E27677fb67531eb09134fE331C27899f87ADe10'
            TOKEN_NAME='tECLD'
            RPC_URL='https://polygon-amoy-bor-rpc.publicnode.com'
            RPC_DELAY=200
            CHAIN_ID=80002
            MIDDLEWARE='POA'
            BLOCK_TIME=2
            MINIMUM_GAS_AT_START=100000000000000000
            GAS_PRICE_MEASURE='gwei'
            EIP1559=True
            GAS_PRICE=0
            GAS_LIMIT=0
            MAX_FEE_PER_GAS=64
            MAX_PRIORITY_FEE_PER_GAS=32
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='ecld-pynithy-amoy'
            TRUSTEDZONE_IMAGE='ecld-pynithy-amoy'
            REWARD_TYPE=1
            NETWORK_FEE=5
            ENCLAVE_FEE=10

    class IOTEX:
        class TESTNET:
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0xa7467A6391816be9367a1cC52E0ef0c15FfE3cCC'
            PROTOCOL_ADDRESS='0xD56385A97413Ed80E28B1b54A193b98F2C49c975'
            TOKEN_ADDRESS='0x95Aa17fCFaAB75e8ed7d7DF218045795dCeB9c50'
            HEARTBEAT_CONTRACT_ADDRESS='0x379456B819f61eF775B0Fd80Cf1DbE47399eB6F7'
            TOKEN_NAME='tECLD'
            RPC_URL='https://babel-api.testnet.iotex.io'
            RPC_DELAY=200
            CHAIN_ID=4690
            MIDDLEWARE=None
            BLOCK_TIME=5
            MINIMUM_GAS_AT_START=5000000000000000000
            GAS_PRICE_MEASURE='gwei'
            EIP1559=True
            GAS_PRICE=0
            GAS_LIMIT=0
            MAX_FEE_PER_GAS=1500
            MAX_PRIORITY_FEE_PER_GAS=1
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='ecld-pynithy-iotex-testnet'
            TRUSTEDZONE_IMAGE='ecld-pynithy-iotex-testnet'
            REWARD_TYPE=2
            NETWORK_FEE=5
            ENCLAVE_FEE=10

    class ETHEREUM:
        class SEPOLIA:
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0x55e0ad455Be85162b71a790f00Fc305680E3CE53'
            PROTOCOL_ADDRESS='0x29D3eC870565B6A1510232bd950A8Bc8336f0EB2'
            TOKEN_ADDRESS='0x95Aa17fCFaAB75e8ed7d7DF218045795dCeB9c50'
            HEARTBEAT_CONTRACT_ADDRESS='0x6D7F920958dfb9a13729723C1007b04eB7950E58'
            TOKEN_NAME='tECLD'
            RPC_URL='https://ethereum-sepolia-rpc.publicnode.com'
            RPC_DELAY=200
            CHAIN_ID=11155111
            MIDDLEWARE=None
            BLOCK_TIME=30
            MINIMUM_GAS_AT_START=200000000000000000
            GAS_PRICE_MEASURE='gwei'
            EIP1559=True
            GAS_PRICE=0
            GAS_LIMIT=0
            MAX_FEE_PER_GAS=15
            MAX_PRIORITY_FEE_PER_GAS=1
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='ecld-pynithy-ethereum-sepolia'
            TRUSTEDZONE_IMAGE='ecld-pynithy-ethereum-sepolia'
            REWARD_TYPE=2
            NETWORK_FEE=5
            ENCLAVE_FEE=10

    class LITVM:
        # LitVM (LiteForge) -- Litecoin EVM ZK-rollup on Arbitrum Orbit, gas
        # token zkLTC. The type name is LITEFORGE (not TESTNET) so the ESR
        # lookup key the runner builds, address_{network}_{type}, matches the
        # 'address_litvm_liteforge' entry in contract/abi/esrAbi.py.
        class LITEFORGE:
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0x55e0ad455Be85162b71a790f00Fc305680E3CE53'
            PROTOCOL_ADDRESS='0x29D3eC870565B6A1510232bd950A8Bc8336f0EB2'
            TOKEN_ADDRESS='0x95Aa17fCFaAB75e8ed7d7DF218045795dCeB9c50'
            HEARTBEAT_CONTRACT_ADDRESS='0x6D7F920958dfb9a13729723C1007b04eB7950E58'
            TOKEN_NAME='tECLD'
            RPC_URL='https://liteforge.rpc.caldera.xyz/infra-partner-http'
            RPC_DELAY=200
            CHAIN_ID=4441
            MIDDLEWARE=None
            BLOCK_TIME=1
            MINIMUM_GAS_AT_START=200000000000000000
            GAS_PRICE_MEASURE='gwei'
            EIP1559=True
            GAS_PRICE=0
            GAS_LIMIT=0
            # Measured base fee is 0.01 gwei and LitVM suggests no tip, so the
            # ceiling of 2 gwei leaves ample headroom over base*1.1.
            MAX_FEE_PER_GAS=2
            MAX_PRIORITY_FEE_PER_GAS=0
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='ecld-pynithy-litvm-testnet'
            TRUSTEDZONE_IMAGE='ecld-pynithy-litvm-testnet'
            REWARD_TYPE=2
            NETWORK_FEE=5
            ENCLAVE_FEE=10

        class LITEFORGE_UNSAFE(LITEFORGE):
            # The chain and contracts of LITEFORGE, with the trustedzones that
            # run without a CAS: a task chosen to run unsafe names this
            # network.
            INTEGRATION_TEST_IMAGE='ecld-pynithy-litvm-testnet-unsafe'
            TRUSTEDZONE_IMAGE='ecld-pynithy-litvm-testnet-unsafe'

ZERO_CHECKSUM = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class ECError(Enum):
    PARSE_ERROR = "The result is not a valid v3 result"
    IPFS_DOWNLOAD_ERROR = "Unable to download results, will keep trying until the download is complete."

class ECLog(IntEnum):
    ERROR = 1
    WARNING = 2
    INFO = 3
    DEBUG = 4