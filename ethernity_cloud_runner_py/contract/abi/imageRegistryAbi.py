contract = {
    "address_bloxberg": "0x15D73a742529C3fb11f3FA32EF7f0CC3870ACA31",
    "address_polygon": "0x689f3806874d3c8A973f419a4eB24e6fBA7E830F",
    "abi": [
        {"inputs": [], "stateMutability": "nonpayable", "type": "constructor"},
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "wallet",
                    "type": "address",
                }
            ],
            "name": "AllowedWalletAdded",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "wallet",
                    "type": "address",
                }
            ],
            "name": "AllowedWalletRemoved",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": False,
                    "internalType": "string",
                    "name": "ipfsHash",
                    "type": "string",
                },
                {
                    "indexed": False,
                    "internalType": "string",
                    "name": "publicKey",
                    "type": "string",
                },
                {
                    "indexed": False,
                    "internalType": "string",
                    "name": "version",
                    "type": "string",
                },
            ],
            "name": "ImageAdded",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": False,
                    "internalType": "string",
                    "name": "ipfsHash",
                    "type": "string",
                }
            ],
            "name": "ImageRemoved",
            "type": "event",
        },
        {
            "inputs": [
                {"internalType": "address", "name": "wallet", "type": "address"}
            ],
            "name": "addAllowedWallet",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "string", "name": "ipfsHash", "type": "string"},
                {"internalType": "string", "name": "certPublicKey", "type": "string"},
                {"internalType": "string", "name": "version", "type": "string"},
                {"internalType": "string", "name": "imageName", "type": "string"},
                {
                    "internalType": "string",
                    "name": "dockerComposeHash",
                    "type": "string",
                },
            ],
            "name": "addImage",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "string", "name": "imageName", "type": "string"},
                {"internalType": "string", "name": "version", "type": "string"},
            ],
            "name": "getLatestTrustedZoneImageCertPublicKey",
            "outputs": [
                {"internalType": "string", "name": "", "type": "string"},
                {"internalType": "string", "name": "", "type": "string"},
                {"internalType": "string", "name": "", "type": "string"},
            ],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "string", "name": "imageName", "type": "string"},
                {"internalType": "string", "name": "version", "type": "string"},
            ],
            "name": "getLatestImageVersionPublicKey",
            "outputs": [
                {"internalType": "string", "name": "", "type": "string"},
                {"internalType": "string", "name": "", "type": "string"},
                {"internalType": "string", "name": "", "type": "string"},
            ],
            "stateMutability": "view",
            "type": "function",
        },
    ],
}
