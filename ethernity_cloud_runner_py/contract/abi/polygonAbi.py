import os

contract = {
    "address": os.getenv(
        "ECLD_CONTRACT_ADDRESS", "0x439945BE73fD86fcC172179021991E96Beff3Cc4"
    ),
    "abi": [
        {
            "constant": False,
            "inputs": [
                {"internalType": "uint8", "name": "_cpuRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "_memRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "_storageRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "_bandwidthRequest", "type": "uint8"},
                {"internalType": "uint16", "name": "_duration", "type": "uint16"},
                {"internalType": "uint8", "name": "_instances", "type": "uint8"},
                {"internalType": "uint8", "name": "_maxPrice", "type": "uint8"},
                {"internalType": "string", "name": "_metadata1", "type": "string"},
                {"internalType": "string", "name": "_metadata2", "type": "string"},
                {"internalType": "string", "name": "_metadata3", "type": "string"},
                {"internalType": "string", "name": "_metadata4", "type": "string"},
            ],
            "name": "_addDORequest",
            "outputs": [
                {"internalType": "uint256", "name": "_rowNumber", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "uint8", "name": "_cpuRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "_memRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "_storageRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "_bandwidthRequest", "type": "uint8"},
                {"internalType": "uint16", "name": "_duration", "type": "uint16"},
                {"internalType": "uint8", "name": "_minPrice", "type": "uint8"},
                {"internalType": "string", "name": "_metadata1", "type": "string"},
                {"internalType": "string", "name": "_metadata2", "type": "string"},
                {"internalType": "string", "name": "_metadata3", "type": "string"},
                {"internalType": "string", "name": "_metadata4", "type": "string"},
            ],
            "name": "_addDPRequest",
            "outputs": [
                {"internalType": "uint256", "name": "_rowNumber", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_doRequestItem",
                    "type": "uint256",
                },
                {
                    "internalType": "uint256",
                    "name": "_dpRequestItem",
                    "type": "uint256",
                },
            ],
            "name": "_placeOrder",
            "outputs": [
                {"internalType": "uint256", "name": "_orderNumber", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "tokenOwner",
                    "type": "address",
                },
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "spender",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "tokens",
                    "type": "uint256",
                },
            ],
            "name": "Approval",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "_from",
                    "type": "address",
                },
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "_to",
                    "type": "address",
                },
            ],
            "name": "OwnershipTransferred",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "_from",
                    "type": "address",
                },
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "_to",
                    "type": "address",
                },
            ],
            "name": "ProxyTransferred",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "from",
                    "type": "address",
                },
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "to",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "tokens",
                    "type": "uint256",
                },
            ],
            "name": "Transfer",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "_from",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "_rowNumber",
                    "type": "uint256",
                },
            ],
            "name": "_addDORequestEV",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "_from",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "_rowNumber",
                    "type": "uint256",
                },
            ],
            "name": "_addDPRequestEV",
            "type": "event",
        },
        {
            "constant": False,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                },
                {"internalType": "string", "name": "_key", "type": "string"},
                {"internalType": "string", "name": "_value", "type": "string"},
            ],
            "name": "_addMetadataToDPRequest",
            "outputs": [
                {"internalType": "uint256", "name": "_rowNumber", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                },
                {"internalType": "string", "name": "_key", "type": "string"},
                {"internalType": "string", "name": "_value", "type": "string"},
            ],
            "name": "_addMetadataToRequest",
            "outputs": [
                {"internalType": "uint256", "name": "_rowNumber", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "uint256", "name": "_orderItem", "type": "uint256"},
                {"internalType": "address", "name": "processor", "type": "address"},
            ],
            "name": "_addProcessorToOrder",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "uint256", "name": "_orderItem", "type": "uint256"},
                {"internalType": "string", "name": "_result", "type": "string"},
            ],
            "name": "_addResultToOrder",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [{"internalType": "address", "name": "addr", "type": "address"}],
            "name": "_addToPresaleRound",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [{"internalType": "address", "name": "addr", "type": "address"}],
            "name": "_addToPrivateSaleRound",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [{"internalType": "address", "name": "addr", "type": "address"}],
            "name": "_addToPublicOneRound",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [{"internalType": "address", "name": "addr", "type": "address"}],
            "name": "_addToPublicTwoRound",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [{"internalType": "address", "name": "addr", "type": "address"}],
            "name": "_addToSeedRound",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "uint256", "name": "_orderItem", "type": "uint256"}
            ],
            "name": "_approveOrder",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_cancelDORequest",
            "outputs": [],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_cancelDPRequest",
            "outputs": [],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "_downer",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "address",
                    "name": "_dproc",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "_orderNumber",
                    "type": "uint256",
                },
            ],
            "name": "_orderApprovedEV",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "_orderNumber",
                    "type": "uint256",
                }
            ],
            "name": "_orderClosedEV",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "_orderNumber",
                    "type": "uint256",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "_doRequestId",
                    "type": "uint256",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "_dpRequestId",
                    "type": "uint256",
                },
            ],
            "name": "_orderPlacedEV",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "_from",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "_orderNumber",
                    "type": "uint256",
                },
            ],
            "name": "_placeOrderEV",
            "type": "event",
        },
        {
            "constant": False,
            "inputs": [{"internalType": "address", "name": "addr", "type": "address"}],
            "name": "_removeLockoutTimestamp",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "uint128", "name": "timestamp", "type": "uint128"}
            ],
            "name": "_setBaseLockTimestamp",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [],
            "name": "acceptOwnership",
            "outputs": [],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "address", "name": "spender", "type": "address"},
                {"internalType": "uint256", "name": "tokens", "type": "uint256"},
            ],
            "name": "approve",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "address", "name": "spender", "type": "address"},
                {"internalType": "uint256", "name": "tokens", "type": "uint256"},
                {"internalType": "bytes", "name": "data", "type": "bytes"},
            ],
            "name": "approveAndCall",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [],
            "name": "faucet",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "tokens", "type": "uint256"},
            ],
            "name": "transfer",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "address", "name": "from", "type": "address"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "tokens", "type": "uint256"},
            ],
            "name": "transfer",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "address", "name": "tokenAddress", "type": "address"},
                {"internalType": "uint256", "name": "tokens", "type": "uint256"},
            ],
            "name": "transferAnyERC20Token",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "address", "name": "from", "type": "address"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "tokens", "type": "uint256"},
            ],
            "name": "transferFrom",
            "outputs": [{"internalType": "bool", "name": "success", "type": "bool"}],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "address", "name": "_newOwner", "type": "address"}
            ],
            "name": "transferOwnership",
            "outputs": [],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "constant": False,
            "inputs": [
                {"internalType": "address", "name": "_newProxy", "type": "address"}
            ],
            "name": "transferProxy",
            "outputs": [],
            "payable": False,
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {"payable": True, "stateMutability": "payable", "type": "fallback"},
        {
            "constant": True,
            "inputs": [],
            "name": "_getBaseLockTimestamp",
            "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_getDORequest",
            "outputs": [
                {"internalType": "address", "name": "downer", "type": "address"},
                {"internalType": "uint8", "name": "cpuRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "memoryRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "storageRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "bandwidthRequest", "type": "uint8"},
                {"internalType": "uint16", "name": "duration", "type": "uint16"},
                {"internalType": "uint8", "name": "maxPrice", "type": "uint8"},
                {"internalType": "uint256", "name": "status", "type": "uint256"},
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_getDORequestMetadata",
            "outputs": [
                {"internalType": "address", "name": "downer", "type": "address"},
                {"internalType": "string", "name": "metadata1", "type": "string"},
                {"internalType": "string", "name": "metadata2", "type": "string"},
                {"internalType": "string", "name": "metadata3", "type": "string"},
                {"internalType": "string", "name": "metadata4", "type": "string"},
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "_getDORequestsCount",
            "outputs": [
                {"internalType": "uint256", "name": "_length", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_getDPRequest",
            "outputs": [
                {"internalType": "address", "name": "dproc", "type": "address"},
                {"internalType": "uint8", "name": "cpuRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "memoryRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "storageRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "bandwidthRequest", "type": "uint8"},
                {"internalType": "uint16", "name": "duration", "type": "uint16"},
                {"internalType": "uint8", "name": "minPrice", "type": "uint8"},
                {"internalType": "uint256", "name": "status", "type": "uint256"},
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_getDPRequestMetadata",
            "outputs": [
                {"internalType": "address", "name": "dproc", "type": "address"},
                {"internalType": "string", "name": "metadata1", "type": "string"},
                {"internalType": "string", "name": "metadata2", "type": "string"},
                {"internalType": "string", "name": "metadata3", "type": "string"},
                {"internalType": "string", "name": "metadata4", "type": "string"},
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "_getDPRequestsCount",
            "outputs": [
                {"internalType": "uint256", "name": "_length", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_getDPRequestWithCreationDate",
            "outputs": [
                {"internalType": "address", "name": "dproc", "type": "address"},
                {"internalType": "uint8", "name": "cpuRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "memoryRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "storageRequest", "type": "uint8"},
                {"internalType": "uint8", "name": "bandwidthRequest", "type": "uint8"},
                {"internalType": "uint16", "name": "duration", "type": "uint16"},
                {"internalType": "uint8", "name": "minPrice", "type": "uint8"},
                {"internalType": "uint256", "name": "status", "type": "uint256"},
                {"internalType": "uint32", "name": "createdAt", "type": "uint32"},
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [{"internalType": "address", "name": "addr", "type": "address"}],
            "name": "_getLockoutTimestamp",
            "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_getMetadataCountForDPRequest",
            "outputs": [
                {"internalType": "uint256", "name": "_length", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                }
            ],
            "name": "_getMetadataCountForRequest",
            "outputs": [
                {"internalType": "uint256", "name": "_length", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                },
                {"internalType": "uint256", "name": "_metadataItem", "type": "uint256"},
            ],
            "name": "_getMetadataValueForDPRequest",
            "outputs": [
                {"internalType": "string", "name": "key", "type": "string"},
                {"internalType": "string", "name": "value", "type": "string"},
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {
                    "internalType": "uint256",
                    "name": "_requestListItem",
                    "type": "uint256",
                },
                {"internalType": "uint256", "name": "_metadataItem", "type": "uint256"},
            ],
            "name": "_getMetadataValueForRequest",
            "outputs": [
                {"internalType": "string", "name": "key", "type": "string"},
                {"internalType": "string", "name": "value", "type": "string"},
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "_getMyDOOrders",
            "outputs": [
                {"internalType": "uint256[]", "name": "req", "type": "uint256[]"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "_getMyDORequests",
            "outputs": [
                {"internalType": "uint256[]", "name": "req", "type": "uint256[]"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "_getMyDPRequests",
            "outputs": [
                {"internalType": "uint256[]", "name": "req", "type": "uint256[]"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {"internalType": "uint256", "name": "_orderItem", "type": "uint256"}
            ],
            "name": "_getOrder",
            "outputs": [
                {"internalType": "address", "name": "downer", "type": "address"},
                {"internalType": "address", "name": "dproc", "type": "address"},
                {"internalType": "uint256", "name": "doRequest", "type": "uint256"},
                {"internalType": "uint256", "name": "dpRequest", "type": "uint256"},
                {"internalType": "uint256", "name": "status", "type": "uint256"},
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "_getOrdersCount",
            "outputs": [
                {"internalType": "uint256", "name": "_length", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {"internalType": "uint256", "name": "_orderItem", "type": "uint256"}
            ],
            "name": "_getResultFromOrder",
            "outputs": [
                {"internalType": "string", "name": "_Result", "type": "string"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "_totalSupply",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {"internalType": "address", "name": "tokenOwner", "type": "address"},
                {"internalType": "address", "name": "spender", "type": "address"},
            ],
            "name": "allowance",
            "outputs": [
                {"internalType": "uint256", "name": "remaining", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [
                {"internalType": "address", "name": "tokenOwner", "type": "address"}
            ],
            "name": "balanceOf",
            "outputs": [
                {"internalType": "uint256", "name": "balance", "type": "uint256"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "callerAddress",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "implementation",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "implementationPro",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "name",
            "outputs": [{"internalType": "string", "name": "", "type": "string"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "newOwner",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "owner",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "symbol",
            "outputs": [{"internalType": "string", "name": "", "type": "string"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
        {
            "constant": True,
            "inputs": [],
            "name": "totalSupply",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "payable": False,
            "stateMutability": "view",
            "type": "function",
        },
    ],
}
