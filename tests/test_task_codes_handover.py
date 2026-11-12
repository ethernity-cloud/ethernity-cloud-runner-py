"""The task codes the trustedzone asserts at a handover or a termination
(41, 42, 43) and the session notice 54 are named; parse_transaction_bytes
recovers version, task code, checksum and challenge from a signed
_addResultToOrder transaction carrying each of the seven result-v5.json
example strings."""
import json
from pathlib import Path

import pytest
from eth_account import Account
from web3 import Web3

from ethernity_cloud_runner_py.contract.abi.polygonProtocolAbi import contract as polygon_abi
from ethernity_cloud_runner_py.enums import (
    ECOrderTaskStatus,
    OPERATOR_FAULT_CODES,
    task_status_name,
)
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from ethernity_cloud_runner_py.session import SESSION_ERROR_CODE_NAMES, SESSION_STATUS_NAMES

FIXTURE = json.loads(
    (Path(__file__).resolve().parent / "spec" / "result-v5.json").read_text(encoding="utf-8"))
EXAMPLES = FIXTURE["examples"]
ORDER_ID = 7
SIGNER = Account.from_key("0x" + "11" * 32)


def test_handover_and_termination_codes_are_named():
    assert task_status_name(41) == "SERVICE_TRANSFERRED"
    assert task_status_name(42) == "SERVICE_TRANSFER_FORCED"
    assert task_status_name(43) == "TERMINATED"
    assert task_status_name(44) == "UNKNOWN_44"


def test_handover_and_termination_codes_are_not_operator_faults():
    assert not OPERATOR_FAULT_CODES & {41, 42, 43}
    assert OPERATOR_FAULT_CODES == {37, 39, 40}


def test_the_table_matches_the_fixture_constants():
    constants = FIXTURE["constants"]
    assert ECOrderTaskStatus[constants["serviceTransferredCode"]] == "SERVICE_TRANSFERRED"
    assert ECOrderTaskStatus[constants["serviceTransferForcedCode"]] == "SERVICE_TRANSFER_FORCED"


def test_session_notice_54_and_the_session_statuses_are_named():
    assert SESSION_ERROR_CODE_NAMES[54] == "session-replay-unavailable"
    codes = FIXTURE["constants"]["sessionStatusCodes"]
    assert codes["transferred"] == 6 and codes["transfer-forced"] == 7
    assert {code: name for name, code in codes.items()} == SESSION_STATUS_NAMES


def _signed_result_transaction(result: str) -> str:
    data = Web3().eth.contract(abi=polygon_abi["abi"]).encode_abi(
        "_addResultToOrder", args=[ORDER_ID, result])
    signed = SIGNER.sign_transaction({
        "nonce": 0, "gasPrice": 1, "gas": 200000, "to": "0x" + "22" * 20,
        "value": 0, "data": data, "chainId": 80002,
    })
    return signed.raw_transaction.hex()


@pytest.mark.parametrize("name", list(EXAMPLES), ids=list(EXAMPLES))
def test_parse_transaction_bytes_reads_every_v5_example(name):
    example = EXAMPLES[name]
    fields = {f["name"]: f["value"] for f in example["fields"]}
    runner = EthernityCloudRunner("LOCAL", "LOCAL")
    runner.protocol_abi = polygon_abi["abi"]

    parsed = runner.parse_transaction_bytes(_signed_result_transaction(example["result"]))

    assert parsed["version"] == "v5"
    assert parsed["task_code"] == fields["taskCode"]
    assert parsed["task_code_int"] == int(fields["taskCode"])
    assert parsed["task_code_string"] == task_status_name(int(fields["taskCode"]))
    assert parsed["checksum"] == fields["resultChecksum"]
    assert parsed["enclave_challenge"] == fields["enclaveChallenge"]
    assert parsed["order_id"] == ORDER_ID
    assert parsed["chain_id"] == 80002
    assert parsed["from"] == SIGNER.address


def test_the_transfer_examples_carry_the_handover_codes():
    codes = {name: int(ex["inputs"]["taskCode"]) for name, ex in EXAMPLES.items()}
    assert codes["transferred"] == 41
    assert codes["forced"] == 42
    assert task_status_name(codes["transferred"]) == "SERVICE_TRANSFERRED"
    assert task_status_name(codes["forced"]) == "SERVICE_TRANSFER_FORCED"
