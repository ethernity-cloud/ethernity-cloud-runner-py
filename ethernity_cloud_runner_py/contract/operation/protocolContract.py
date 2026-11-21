from decimal import Decimal
import os
import re
from typing import Any, Union
from eth_account.messages import encode_defunct
from eth_typing import Address, HexStr
from web3 import Web3
from web3.contract.contract import Contract
from web3.contract.contract import ContractFunction
from web3.middleware import ExtraDataToPOAMiddleware
from web3.types import TxParams
from web3.exceptions import Web3RPCError
import requests
from ..abi.polygonProtocolAbi import contract as polygonAbi
from ..abi.ECLDAbi import contract as ECLDAbi
from ...enums import ECNetwork
from ...errors import (suppress_web3_friendly_prefix, raw_rpc_error_message, raw_rpc_error_code, provider_message,
                       FeeCeilingError, RunEndedError)
from ...rpc import rpc_session

# The environment variable that names the fee ceiling, a positive whole number
# of gwei, where EthernityCloudRunner.set_max_fee_per_gas gave none
# (protocolContract.fee_ceiling).
MAX_FEE_PER_GAS_ENV = "ECLD_MAX_FEE_PER_GAS"


def _gwei(wei: int) -> str:
    """`wei` in gwei as exact decimal text, without trailing zeros."""
    whole, fraction = divmod(wei, 10**9)
    return f"{whole}.{fraction:09d}".rstrip("0").rstrip(".")


class protocolContract:

    # The _addDORequest arguments, with the values a resources dict leaves out.
    REQUEST_DEFAULTS = {
        "cpu": 1,
        "memory": 1,
        "storage": 40,
        "bandwidth": 1,
        "duration": 1,
        "validators": 1,
        "taskPrice": 10,
    }

    @classmethod
    def request_terms(cls, resources: dict) -> dict:
        """The _addDORequest arguments of `resources`: its values for the keys
        of REQUEST_DEFAULTS, the defaults for the keys it leaves out."""
        return {key: resources.get(key, default) for key, default in cls.REQUEST_DEFAULTS.items()}

    @classmethod
    def request_escrow(cls, resources: dict) -> int:
        """The escrow of a _addDORequest for `resources`: the task price of
        every instance over the duration, taskPrice * validators * duration.
        The EthernityImplementationV2 pulls it from the caller with
        transferFrom (Ethernity20Extension._addDORequest:
        _tokensToWeis(_maxPrice) * _instances * _duration); the bloxberg
        mainnet PoX requires the caller's balance to cover it
        (Ethernity.sol _addDORequest: balances[msg.sender] >= _maxPrice *
        _instances * _duration * 10**18) and transfers _maxPrice * _duration
        tokens of it to itself in the same call."""
        terms = cls.request_terms(resources)
        return terms["taskPrice"] * terms["validators"] * terms["duration"]

    def __init__(
        self, signer: Any, network_name="BLOXBERG", network_type="TESTNET", request_kwargs=None,
        max_fee_per_gas=None,
    ) -> None:

        # Access the network class (e.g., ECNetwork.BLOXBERG)
        network_class = getattr(ECNetwork, network_name.upper())

        # Access the network type class within the network class (e.g., ECNetwork.BLOXBERG.TESTNET)
        self.network_config = getattr(network_class, network_type.upper())
        self.chain_id = self.network_config.CHAIN_ID
        self.token_address =  self.network_config.TOKEN_ADDRESS
        self.protocol_address = self.network_config.PROTOCOL_ADDRESS
        # The fee ceiling EthernityCloudRunner.set_max_fee_per_gas gave, in
        # gwei; None where it gave none (fee_ceiling).
        self.max_fee_per_gas = max_fee_per_gas
        self.max_priority_fee_per_gas = self.network_config.MAX_PRIORITY_FEE_PER_GAS
        _rpc_url = self.network_config.RPC_URL
        self.provider = Web3(Web3.HTTPProvider(_rpc_url, request_kwargs=request_kwargs or {'timeout': 10},
                                               session=rpc_session()))
        if self.network_config.MIDDLEWARE == "POA":
            self.provider.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.signer = signer
        # What retire() was given: why this contract sends nothing more. None
        # while it sends.
        self.retired = None
        self.protocol_contract = self.provider.eth.contract(
            address=self.protocol_address, abi=polygonAbi["abi"]
        )
        self.token_contract = self.provider.eth.contract(
            address=self.token_address, abi=ECLDAbi["abi"]
        )
    def retire(self, reason: str) -> None:
        """Ends this contract's sends. `reason` says what its runner did (it
        was closed, moved to another network, given another wallet): every
        transaction asked of the contract after it raises
        errors.RunEndedError with that reason and is not sent
        (_build_sign_send). The reads go on."""
        self.retired = reason
    def _refuse_retired(self) -> None:
        """Raises errors.RunEndedError on a contract retire() ended."""
        if self.retired is not None:
            raise RunEndedError(
                f"{self.retired}, and the protocol contract it held until then sends nothing after that: "
                "the transaction was not sent.")
    def get_token_address(self) -> Address:
        return self.token_address
    def get_protocol_address(self) -> Address:
        return self.protocol_address
    def fee_ceiling(self) -> tuple:
        """(wei, source): the ceiling a transaction's maxFeePerGas is checked
        against on a network whose table entry says EIP1559, and what set it,
        in the words the refusal's message gives it. In this order: the value
        EthernityCloudRunner.set_max_fee_per_gas gave (self.max_fee_per_gas,
        gwei); the environment variable ECLD_MAX_FEE_PER_GAS when it is set
        and not empty, read at each send, a positive whole number of gwei in
        ASCII digits alone, at most 30 of them, as ethernity-cloud-sdk-py
        reads the same variable (any other value raises FeeCeilingError
        naming the variable and the value); the table entry's
        MAX_FEE_PER_GAS."""
        if self.max_fee_per_gas is not None:
            return self.max_fee_per_gas * 10**9, "set with set_max_fee_per_gas"
        value = os.environ.get(MAX_FEE_PER_GAS_ENV)
        if value:
            gwei = int(value) if re.fullmatch(r"[0-9]{1,30}", value) else 0
            if not gwei:
                raise FeeCeilingError(
                    f"The environment variable {MAX_FEE_PER_GAS_ENV} is {value!r}, which is not a positive "
                    "whole number of gwei, so the transaction was not sent. Set it to the fee ceiling in "
                    "whole gwei, or unset it to send within the network's default.")
            return gwei * 10**9, f"set by the environment variable {MAX_FEE_PER_GAS_ENV}"
        return (Web3.to_wei(self.network_config.MAX_FEE_PER_GAS, self.network_config.GAS_PRICE_MEASURE),
                "the network's default")
    def __transaction_object(self, nonce=None) -> TxParams:
        """The fee and nonce fields of a transaction. It carries no gas limit:
        build_transaction then asks the node for the call's estimate, which
        _build_sign_send sizes (a fixed figure sent an approve out of gas on
        Sepolia, whose schedule prices a new storage slot several times the
        local EVM's). The type is the hex string "0x2": build_transaction
        passes the field to eth_estimateGas as given, and Tenderly's gateway
        refuses the number 2. On a network whose table entry says EIP1559 a
        maxFeePerGas above fee_ceiling() raises FeeCeilingError; another
        network sends at the entry's GAS_PRICE and reads no ceiling."""
        if nonce is None:
            nonce = self.provider.eth.get_transaction_count(self.signer.address, "pending")

        if self.network_config.EIP1559 == True:
            ceiling, source = self.fee_ceiling()
            latest_block = self.provider.eth.get_block("latest")
            max_fee_per_gas = int(latest_block.baseFeePerGas * 1.1) + self.provider.to_wei(self.network_config.MAX_PRIORITY_FEE_PER_GAS, self.network_config.GAS_PRICE_MEASURE) # 10% increase in previous block gas price + priority fee
            if max_fee_per_gas > ceiling:
                priority_fee = self.provider.to_wei(self.network_config.MAX_PRIORITY_FEE_PER_GAS, self.network_config.GAS_PRICE_MEASURE)
                raise FeeCeilingError(
                    f"The network's base fee is {_gwei(latest_block.baseFeePerGas)} gwei; the maxFeePerGas "
                    f"computed for the transaction, {_gwei(max_fee_per_gas)} gwei (the base fee plus 10 %, "
                    f"plus the priority fee of {_gwei(priority_fee)} gwei), is above the fee ceiling of "
                    f"{_gwei(ceiling)} gwei ({source}), so the transaction was not sent. To send at this fee, "
                    "raise the ceiling with EthernityCloudRunner.set_max_fee_per_gas(gwei) or, where that was "
                    f"not called, with the environment variable {MAX_FEE_PER_GAS_ENV} (a whole number of gwei).")

            transaction_options = {
                "type": "0x2",
                "nonce": nonce,
                "chainId": self.chain_id,
                "from": self.signer.address,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': self.provider.to_wei(self.network_config.MAX_PRIORITY_FEE_PER_GAS, self.network_config.GAS_PRICE_MEASURE),
            }
        else:
            transaction_options = {
                "nonce": nonce,
                "chainId": self.chain_id,
                "from": self.signer.address,
                "gasPrice": self.provider.to_wei(self.network_config.GAS_PRICE, self.network_config.GAS_PRICE_MEASURE),
            }
        return transaction_options


    def _build_sign_send(self, contract_fn: ContractFunction, gas: int) -> HexStr:
        """
        Build, sign, and send a transaction with retry logic and special handling
        for nonce-related Web3RPCError codes (-32000, -32010). A FeeCeilingError
        is printed like any other failure of an attempt and raised as it is,
        with no further attempt. A contract retire() ended raises
        RunEndedError: before an attempt reads the nonce and the fee, and
        again before the signed transaction is handed to the node.
        """
        max_attempts = 20
        current_nonce = None

        for attempt in range(max_attempts):
            self._refuse_retired()
            try:
                options = self.__transaction_object(nonce=current_nonce)
                # build_transaction fills `gas` with the node's estimate for the
                # call on the current state; a quarter on top covers the state
                # moving before the block, and the caller's figure, sized for
                # the local EVM, stays as the floor.
                tx = contract_fn.build_transaction(options)
                tx["gas"] = max(int(tx["gas"] * 1.25), int(gas or 0))
                signed_tx = self.provider.eth.account.sign_transaction(
                    tx, private_key=self.signer._private_key
                )
                self._refuse_retired()

                # Suppress Web3's friendly prefix for this call only
                with suppress_web3_friendly_prefix():
                    tx_hash = self.provider.eth.send_raw_transaction(signed_tx.raw_transaction)

                hex_tx_hash = self.provider.to_hex(tx_hash)

                return hex_tx_hash

            except Web3RPCError as e:
                node_message = raw_rpc_error_message(e)
                error_code = raw_rpc_error_code(e)

                error_str = node_message.lower()
                if error_code in (-32000, -32010):
                    if "nonce too low" in error_str:
                        current_nonce = None  # refetch next time
                    elif any(
                        phrase in error_str
                        for phrase in [
                            "same nonce in the queue",
                            "replacement transaction underpriced",
                            "transaction with same nonce in the queue",
                        ]
                    ):
                        if current_nonce is None:
                            current_nonce = options.get("nonce", 0) + 1
                        else:
                            current_nonce += 1
                    else:
                        raise
                    continue
                else:
                    raise

            except Exception as e:
                print(f"Attempt {attempt + 1}: Exception encountered: {str(e)}")
                if isinstance(e, requests.exceptions.Timeout):
                    print(f"Attempt {attempt + 1}: Timeout, retrying...")
                    continue
                elif isinstance(e, (FeeCeilingError, RunEndedError)):
                    raise
                else:
                    raise Exception(f"Unable to send transaction: {str(e)}")

        raise Exception("Max retries exceeded for transaction send")

    def get_signer(self) -> Any:
        return self.signer
    def get_contract(self) -> Contract:
        return self.protocol_contract
    def get_provider(self) -> Web3:
        return self.provider
    def get_current_wallet(self) -> Any:
        return self.signer
    def get_balance(self) -> Union[int, Decimal]:
        """The wallet's balance on the token, in tokens, as Web3.from_wei
        gives it: the int 0 for an empty wallet, a Decimal otherwise. A read
        the RPC does not answer raises RuntimeError naming the token, the
        wallet and the provider's message (errors.provider_message); no figure
        stands in for the balance of a failed read."""
        address = self.signer.address
        try:
            balance = self.token_contract.functions.balanceOf(address).call()
        except Exception as e:
            raise RuntimeError(
                f"could not read the {self.network_config.TOKEN_NAME} balance of {address} "
                f"at {self.token_address}: {provider_message(e)}") from e
        return Web3.from_wei(balance, "ether")
    def set_allowance(
        self, tokens: int
    ) -> HexStr:
        """Approves the protocol for `tokens` on the token: the wallet's
        allowance for the protocol becomes that amount, in wei. Returns the
        approval's transaction hash."""
        contract_fn = self.token_contract.functions.approve(
            self.protocol_address, Web3.to_wei(tokens, "ether")
        )
        return self._build_sign_send(contract_fn, 100000)

    def faucet(
        self
    ) -> bool:
        contract_fn = self.token_contract.functions.faucet()
        return self._build_sign_send(contract_fn, 100000)
    def add_do_request(
        self,
        image_metadata: str,
        payload_metadata: str,
        input_metadata: str,
        node_address: Address,
        resources: dict,
        gas_limit: None = None,
    ) -> HexStr:
        terms = self.request_terms(resources)
        contract_fn = self.protocol_contract.functions._addDORequest(
            terms["cpu"],
            terms["memory"],
            terms["storage"],
            terms["bandwidth"],
            terms["duration"],
            terms["validators"],
            terms["taskPrice"],
            image_metadata,
            payload_metadata,
            input_metadata,
            node_address,
        )
        return self._build_sign_send(contract_fn, 1000000)
    def get_order(self, order_id: int) -> int:
        return self.protocol_contract.functions._getOrder(order_id).call()
    def add_metadata_to_request(self, request_id: int, key: str, value: str) -> HexStr:
        """Append a metadata row to one of THIS wallet's DO requests (the
        contract enforces caller == downer). The interactive-session input
        channel."""
        contract_fn = self.protocol_contract.functions._addMetadataToRequest(
            request_id, key, value
        )
        return self._build_sign_send(contract_fn, 300000)
    def approve_order(self, order_id: int) -> HexStr:
        contract_fn = self.protocol_contract.functions._approveOrder(
            order_id
        )
        return self._build_sign_send(contract_fn, 100000)
    def cancel_do_request(self, request_id: int) -> HexStr:
        contract_fn = self.protocol_contract.functions._cancelDORequest(
            request_id
        )
        return self._build_sign_send(contract_fn, 200000)
    def get_result_from_order(self, order_id: int) -> Any:
        self.protocol_contract.caller()._getOrder(order_id)
        return self.protocol_contract.caller()._getResultFromOrder(order_id)
    def get_status_from_order(self, order_id: int) -> Any:
        return self.protocol_contract.caller()._getOrder(order_id)[4]
    def get_orders_count(self) -> int:
        """The number of orders placed on this PoX (_getOrdersCount). A read
        the contract or the RPC refuses is raised."""
        return self.protocol_contract.functions._getOrdersCount().call()
    # The reads storage_admission makes: the EthernityCloudStorage an
    # EthernityImplementationV2 names, and that storage's allow-list.
    STORAGE_POINTER_ABI = [{"inputs": [], "name": "ethStorageAddress",
                            "outputs": [{"name": "", "type": "address"}],
                            "stateMutability": "view", "type": "function"}]
    ALLOWED_CALLERS_ABI = [{"inputs": [{"name": "", "type": "address"}], "name": "allowedCallers",
                            "outputs": [{"name": "", "type": "bool"}],
                            "stateMutability": "view", "type": "function"}]

    def is_node_operator(self, account: str) -> bool:
        """Whether `account` holds a DP request on this PoX. The read is made
        from the address in its EIP-55 form, the only spelling web3 takes as
        a call's `from`; `account` is an address in any spelling
        utils.is_address admits. A read the contract or the RPC refuses is
        raised: it says nothing about the account."""
        requests = self.protocol_contract.functions._getMyDPRequests().call(
            {"from": Web3.to_checksum_address(account)}
        )
        return len(requests) > 0

    def storage_admission(self):
        """(storage, admitted): the EthernityCloudStorage this implementation
        names (ethStorageAddress) and whether that storage lists the
        implementation among its allowed callers; None when either read
        fails. The storage refuses every call, reads included, made through
        an implementation it does not list ("Allowed caller: caller is not
        allowed"); its owner takes an implementation off the list when
        another one replaces it."""
        try:
            pointer = self.provider.eth.contract(address=self.protocol_address, abi=self.STORAGE_POINTER_ABI)
            storage = pointer.functions.ethStorageAddress().call()
            allow_list = self.provider.eth.contract(address=storage, abi=self.ALLOWED_CALLERS_ABI)
            return storage, bool(allow_list.functions.allowedCallers(self.protocol_address).call())
        except Exception:
            return None
    def sign_message(self, message: str) -> Any:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        return self.provider.eth.account.sign_message(
            encode_defunct(text=message), self.signer._private_key
        )