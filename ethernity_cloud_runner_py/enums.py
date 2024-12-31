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


ECNetworkByChainId = {
    "BLOXBERG": {"TESTNET": 8995, "MAINNET": 8995},
    "POLYGON": {"AMOY": 80002, "MAINNET": 137},
}

ECNetworkByChainIdDictionary = {8995: "bloxberg", 80002: "amoy", 137: "matic"}


class ECNetwork:
    class BLOXBERG:
        TESTNET = "Bloxberg TESTNET"
        MAINNET = "Bloxberg MAINNET"

    class POLYGON:
        TESTNET = "Polygon TESTNET"
        MAINNET = "Polygon MAINNET"


class ECRunner:
    BLOXBERG = {
        "PYNITHY_RUNNER_TESTNET": "etny-pynithy-testnet",
        "NODENITHY_RUNNER_TESTNET": "etny-nodenithy-testnet",
        "PYNITHY_RUNNER_MAINNET": "etny-pynithy",
        "NODENITHY_RUNNER_MAINNET": "etny-nodenithy"
    }
    POLYGON = {
        "PYNITHY_RUNNER_AMOY": "ecld-pynithy-amoy",
        "NODENITHY_RUNNER_AMOY": "ecld-nodenithy-amoy",
        "PYNITHY_RUNNER_MAINNET": "ecld-pynithy",
        "NODENITHY_RUNNER_MAINNET": "ecld-nodenithy"
    }
    
    def __getitem__(self, key):
        return getattr(self, key)


class ECAddress:
    class BLOXBERG:
        TESTNET_ADDRESS = "0x02882F03097fE8cD31afbdFbB5D72a498B41112c"
        MAINNET_ADDRESS = "0x549A6E06BB2084100148D50F51CF77a3436C3Ae7"

        class IMAGE_REGISTRY:
            class PYNITHY:
                TESTNET_ADDRESS = "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31"
                MAINNET_ADDRESS = "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31"

            class NODENITHY:
                TESTNET_ADDRESS = "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31"
                MAINNET_ADDRESS = "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31"

    class POLYGON:
        AMOY_ADDRESS = "0x9927809B61122B2af3f3b3A3303875e0687b8eE3"
        AMOY_PROTOCOL_ADDRESS = "0x1579b37C5a69ae02dDd23263A2b1318DE66a27C3"
        MAINNET_ADDRESS = "0xc6920888988cAcEeA7ACCA0c96f2D65b05eE22Ba"
        MAINNET_PROTOCOL_ADDRESS = "0x439945BE73fD86fcC172179021991E96Beff3Cc4"

        class IMAGE_REGISTRY:
            class PYNITHY:
                AMOY_ADDRESS = "0xeFA33c3976f31961285Ae4f5D10188616C912728"
                MAINNET_ADDRESS = "0x689f3806874d3c8A973f419a4eB24e6fBA7E830F"

            class NODENITHY:
                AMOY_ADDRESS = "0xeFA33c3976f31961285Ae4f5D10188616C912728"
                MAINNET_ADDRESS = "0x689f3806874d3c8A973f419a4eB24e6fBA7E830F"


class ECNetworkName(Enum):
    BLOXBERG = "bloxberg"
    MUMBAI = "amoy"
    POLYGON = "matic"
    OTHER = "other"


ECNetworkNameDictionary = {
    ECAddress.BLOXBERG.MAINNET_ADDRESS: "bloxberg",
    ECAddress.BLOXBERG.TESTNET_ADDRESS: "bloxberg",
    ECAddress.POLYGON.AMOY_ADDRESS: "amoy",
    ECAddress.POLYGON.MAINNET_ADDRESS: "matic",
}

ECNetworkName1Dictionary = {
    ECAddress.BLOXBERG.MAINNET_ADDRESS: "BLOXBERG",
    ECAddress.BLOXBERG.TESTNET_ADDRESS: "BLOXBERG",
    ECAddress.POLYGON.AMOY_ADDRESS: "AMOY",
    ECAddress.POLYGON.MAINNET_ADDRESS: "POLYGON",
}

ECNetworkRPCDictionary = {
    ECAddress.BLOXBERG.MAINNET_ADDRESS: "https://bloxberg.ethernity.cloud",
    ECAddress.BLOXBERG.TESTNET_ADDRESS: "https://bloxberg.ethernity.cloud",
    ECAddress.POLYGON.AMOY_ADDRESS: "https://rpc.ankr.com/polygon_amoy",
    ECAddress.POLYGON.MAINNET_ADDRESS: "https://polygon-rpc.com",
}

ECNetworkEnvToEnum = {
    "bloxberg_mainnet": ECAddress.BLOXBERG.MAINNET_ADDRESS,
    "bloxberg_testnet": ECAddress.BLOXBERG.TESTNET_ADDRESS,
    "polygon_amoy": ECAddress.POLYGON.AMOY_ADDRESS,
    "polygon_mainnet": ECAddress.POLYGON.MAINNET_ADDRESS,
}

ZERO_CHECKSUM = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class ECError(Enum):
    PARSE_ERROR = "The result is not a valid v3 result"
    IPFS_DOWNLOAD_ERROR = "Unable to download results, will keep trying until the download is complete."

class ECLog(IntEnum):
    ERROR = 1
    WARNING = 2
    INFO = 3
    DEBUG = 4