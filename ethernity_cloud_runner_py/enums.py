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
}


class ECOrderTaskStatusCode(Enum):
    SUCCESS = "SUCCESS"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    KEY_ERROR = "KEY_ERROR"
    SYNTAX_WARNING = "SYNTAX_WARNING"
    BASE_EXCEPTION = "BASE_EXCEPTION"
    PAYLOAD_NOT_DEFINED = "PAYLOAD_NOT_DEFINED"
    PAYLOAD_CHECKSUM_ERROR = "PAYLOAD_CHECKSUM_ERROR"
    INPUT_CHECKSUM_ERROR = "INPUT_CHECKSUM_ERROR"

class ECNetwork:
    class BLOXBERG:

        class TESTNET:
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31'
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
            RPC_URL='https://rpc.ankr.com/polygon_amoy'
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

ZERO_CHECKSUM = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class ECError(Enum):
    PARSE_ERROR = "The result is not a valid v3 result"
    IPFS_DOWNLOAD_ERROR = "Unable to download results, will keep trying until the download is complete."

class ECLog(IntEnum):
    ERROR = 1
    WARNING = 2
    INFO = 3
    DEBUG = 4