contract = {
    "address": "0x439945BE73fD86fcC172179021991E96Beff3Cc4",
    "abi": [
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
        # Add other function definitions here
    ],
}
