contract = {
    "address": "0x02882F03097fE8cD31afbdFbB5D72a498B41112c",
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
        # Add other function definitions here
    ],
}
