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
    # the securelock alike.
    40: "CAS_ATTESTATION_FAULT",
    # Codes the trustedzone alone asserts at a handover or a termination; none
    # is a refund code. 41 and 42 are result-v5.json's serviceTransferredCode
    # and serviceTransferForcedCode; 43 is the trustedzones' TaskStatus.TERMINATED.
    # The trustedzone signs 41 or 42 from the outputs it holds at the handover,
    # whichever control (close or transfer) it wrote.
    41: "SERVICE_TRANSFERRED",       # the session was handed over to the successor's window
                                     # with every forwarded input answered by its output
    42: "SERVICE_TRANSFER_FORCED",   # the session was handed over with an input unanswered
                                     # (the one in hand or any forwarded behind it)
    43: "TERMINATED",                # a plain task ended by orderTerminatedAt while running
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


# An entry of a PoX 2.0 deployment that carries PoxMatching names it in
# MATCHING_ADDRESS and its PoxMatchReader in MATCH_READER_ADDRESS, and may
# name the roll entries one paged read of the reader asks for in
# MATCH_PAGE_ENTRIES (spec/matching.md section 2: 650 on bloxberg, 800 on
# Polygon and Amoy, 1,450 on LitVM). A request on such a network is served by
# claims while PoxMatching's claimsOn() answers true (EthernityCloudRunner
# ._claims_path). No entry names one: no PoxMatching is deployed.
class ECNetwork:
    class BLOXBERG:

        class TESTNET:
            # ECImageRegistryV3, where the testnet trustedzones and the
            # securelocks published against them are registered: the
            # deployment of 2026-10-06, whose securelock names belong to their
            # publishers.
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0xa372a6e1Eb7Fcf343AF6b91E809b900C55001CD1'
            # The PoX 2.0 implementation of pox-smart-contract-litvm
            # deployed 2026-11-18, whose compute figures are whole GFLOPS, on
            # the EthernityCloudStorage 0xEE3aAa1A... of 2026-11-14. The token
            # stays the legacy proxy 0x02882F03..., which is also the PoX of
            # the orders placed through it. The protocol is not the token, so
            # a DO request's escrow is pulled with transferFrom and the wallet
            # approves the implementation for it first, as on Polygon Amoy
            # (EthernityCloudRunner.escrow_needs_allowance, check_allowance).
            PROTOCOL_ADDRESS='0x830c781F0352050343211B6BFA83600B3e77647C'
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

        class TESTNET_POX10:
            # The bloxberg testnet PoX 1.0 network, bloxberg_testnet_pox10: a
            # copy of the bloxberg mainnet's PoX 1.0 contracts on the same
            # chain (8995), deployed 2026-11-21 from block 30867912. The PoX
            # proxy is its own token, as MAINNET's is, so a DO request's
            # escrow is taken from the caller's balance and no allowance is
            # approved (EthernityCloudRunner.escrow_needs_allowance). The
            # token (name "PoX10 Test ETNY", symbol tE10) has no faucet() and
            # no mint: TOKEN_FAUCET is False, and a wallet below a request's
            # escrow is refused with the amount it lacks
            # (EthernityCloudRunner._check_balance). The image registry is a
            # V1 ECImageRegistry. The trustedzones are signed --production and
            # take their sessions from Scontain's CAS, as MAINNET's do.
            # TRUSTEDZONES names them, the pynithy and the nodenithy one: the
            # runner runs no other trustedzone on this network and runs them
            # on no other (EthernityCloudRunner._resolve_trustedzone).
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0x7dBC1b591cc3b7136D863bc7430C6Db50E929665'
            PROTOCOL_ADDRESS='0x69A7bEB5Da2d3dA711d52E491D71e51296b08745'
            TOKEN_ADDRESS='0x69A7bEB5Da2d3dA711d52E491D71e51296b08745'
            HEARTBEAT_CONTRACT_ADDRESS='0x4426C87484038F9B720a6012A1191DA73bDa0ad3'
            TOKEN_NAME='tE10'
            TOKEN_FAUCET=False
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
            INTEGRATION_TEST_IMAGE='etny-pynithy-testnet-pox10'
            TRUSTEDZONE_IMAGE='etny-pynithy-testnet-pox10'
            TRUSTEDZONES=('etny-pynithy-testnet-pox10', 'etny-nodenithy-testnet-pox10')
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
            # The base fee of blocks 97604709 to 97605732 (2026-11-19) was
            # 196.4 to 261.8 gwei. The ceiling of 500 gwei admits a base fee
            # up to 425.45 gwei: maxFeePerGas is int(baseFee * 1.1) plus the
            # priority fee of 32 gwei.
            MAX_FEE_PER_GAS=500
            MAX_PRIORITY_FEE_PER_GAS=32
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='ecld-pynithy'
            TRUSTEDZONE_IMAGE='ecld-pynithy'
            REWARD_TYPE=1
            NETWORK_FEE=5
            ENCLAVE_FEE=10
        class AMOY:
            # ECImageRegistryV3 of 2026-10-28 and the PoX 2.0 implementation
            # deployed 2026-11-18, whose compute figures are whole GFLOPS, on
            # the storage and token of the implementations 1.1 0xB8f46D2B...
            # and 0x1579b37C.... A DO request is escrowed by the implementation
            # it was posted through, so only this one is served. The token's
            # faucet() gives 1000 tECLD to a wallet holding less than 100:
            # TOKEN_FAUCET_BELOW is that balance, in tokens, and a wallet
            # below a request's escrow draws the faucet only while it holds
            # less (EthernityCloudRunner._check_balance).
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0x0C0f52ebd72cd2d2cBe94F385c9e23cec528b706'
            PROTOCOL_ADDRESS='0xd1182deA61CDa785C320cdBE5888EaC4178cAAF2'
            TOKEN_ADDRESS='0x9927809B61122B2af3f3b3A3303875e0687b8eE3'
            HEARTBEAT_CONTRACT_ADDRESS='0x2E27677fb67531eb09134fE331C27899f87ADe10'
            TOKEN_NAME='tECLD'
            TOKEN_FAUCET_BELOW=100
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
            # The ceiling of 500 gwei admits a base fee up to 425.45 gwei:
            # maxFeePerGas is int(baseFee * 1.1) plus the priority fee of 32
            # gwei.
            MAX_FEE_PER_GAS=500
            MAX_PRIORITY_FEE_PER_GAS=32
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='ecld-pynithy-amoy'
            TRUSTEDZONE_IMAGE='ecld-pynithy-amoy'
            REWARD_TYPE=1
            NETWORK_FEE=5
            ENCLAVE_FEE=10

        class AMOY_UNSAFE(AMOY):
            # The chain and contracts of AMOY, with the trustedzones that run
            # without a CAS (hardware SGX platforms the CAS cannot attest): a
            # task chosen to run unsafe names this network.
            INTEGRATION_TEST_IMAGE='ecld-pynithy-amoy-unsafe'
            TRUSTEDZONE_IMAGE='ecld-pynithy-amoy-unsafe'

        class AMOY_POX10:
            # The Polygon Amoy PoX 1.0 network, polygon_amoy_pox10: a copy of
            # Polygon mainnet's PoX 1.0 contracts on Amoy (80002), deployed
            # 2026-11-21 from block 53417996, on the storage 0x20B9fDBD....
            # The token is AMOY's test ECLD, with AMOY's TOKEN_FAUCET_BELOW
            # (EthernityCloudRunner._check_balance). The PoX is apart from
            # the token, so the wallet approves the PoX for a request's
            # escrow, as on MAINNET. The image registry is a V1
            # ECImageRegistry. The trustedzones are signed --production and
            # take their sessions from Scontain's CAS, as MAINNET's do.
            # TRUSTEDZONES names them, the pynithy and the nodenithy one: the
            # runner runs no other trustedzone on this network and runs them
            # on no other (EthernityCloudRunner._resolve_trustedzone). The
            # RPC, the chain id and the fee values are AMOY's.
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0xa2EE2a9118d0011AF05a6196c862D37d8c29F8eC'
            PROTOCOL_ADDRESS='0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02'
            TOKEN_ADDRESS='0x9927809B61122B2af3f3b3A3303875e0687b8eE3'
            HEARTBEAT_CONTRACT_ADDRESS='0x937F74419E31c1200e86B6D2439D9f12b3Fa12c9'
            TOKEN_NAME='tECLD'
            TOKEN_FAUCET_BELOW=100
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
            # The ceiling of 500 gwei admits a base fee up to 425.45 gwei:
            # maxFeePerGas is int(baseFee * 1.1) plus the priority fee of 32
            # gwei.
            MAX_FEE_PER_GAS=500
            MAX_PRIORITY_FEE_PER_GAS=32
            TASK_EXECUTION_PRICE_DEFAULT=1
            INTEGRATION_TEST_IMAGE='ecld-pynithy-amoy-pox10'
            TRUSTEDZONE_IMAGE='ecld-pynithy-amoy-pox10'
            TRUSTEDZONES=('ecld-pynithy-amoy-pox10', 'ecld-nodenithy-amoy-pox10')
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
            # The ECImageRegistryV3 of 2026-10-14.
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0xa7E43a269E3307cf9d246b07df2B89CAA1b4C42F'
            # The EthernityImplementationV2 1.1 of 2026-10-14, the PoX Sepolia's
            # CAS set validates orders on; its tECLD is the family's own. The
            # previous family (0x29D3eC87..., 0x95Aa17fC...) is abandoned.
            PROTOCOL_ADDRESS='0x798975F9FdD90A21Cb11Ac26F1377e1542c58f9c'
            TOKEN_ADDRESS='0x2E27677fb67531eb09134fE331C27899f87ADe10'
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

        class SEPOLIA_UNSAFE(SEPOLIA):
            # The chain and contracts of SEPOLIA, with the trustedzones that
            # run without a CAS: a task chosen to run unsafe names this
            # network.
            INTEGRATION_TEST_IMAGE='ecld-pynithy-ethereum-sepolia-unsafe'
            TRUSTEDZONE_IMAGE='ecld-pynithy-ethereum-sepolia-unsafe'

    class LITVM:
        # LitVM (LiteForge) -- Litecoin EVM ZK-rollup on Arbitrum Orbit, gas
        # token zkLTC. The type name is LITEFORGE (not TESTNET) so the ESR
        # lookup key the runner builds, address_{network}_{type}, matches the
        # 'address_litvm_liteforge' entry in contract/abi/esrAbi.py.
        class LITEFORGE:
            # The ECImageRegistryV3 of 2026-10-12.
            IMAGE_REGISTRY_CONTRACT_ADDRESS='0xAf8Ce29103E1f59feDD49688ff070Ffc2346AF1D'
            # The EthernityImplementationV2 1.1 of 2026-10-11, the PoX LitVM's
            # CAS set validates orders on.
            PROTOCOL_ADDRESS='0xE35991de1f2A435e29E70406FA2781b1AffCb168'
            TOKEN_ADDRESS='0x95Aa17fCFaAB75e8ed7d7DF218045795dCeB9c50'
            HEARTBEAT_CONTRACT_ADDRESS='0x6D7F920958dfb9a13729723C1007b04eB7950E58'
            TOKEN_NAME='tECLD'
            # Hosted by Zeeve since 2026-11-12 (docs.litvm.com, "add to
            # wallet"); its eth_getLogs serves at most 3000 blocks per call,
            # the bound runner.py's GET_LOGS_MAX_BLOCKS applies.
            RPC_URL='https://rpc.testnet.liteforge.zeeve.net/'
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


def trustedzone_network(trustedzone: str):
    """(network name, network type) of the ECNetwork entry whose TRUSTEDZONES
    names `trustedzone`, the one network that trustedzone runs on; None for a
    trustedzone no entry names in that field."""
    for network_name, network in vars(ECNetwork).items():
        if network_name.startswith("_"):
            continue
        for type_name, entry in vars(network).items():
            if not type_name.startswith("_") and trustedzone in getattr(entry, "TRUSTEDZONES", ()):
                return network_name, type_name
    return None


ZERO_CHECKSUM = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class ECError(Enum):
    PARSE_ERROR = "The result is not a valid v3 result"

class ECLog(IntEnum):
    ERROR = 1
    WARNING = 2
    INFO = 3
    DEBUG = 4