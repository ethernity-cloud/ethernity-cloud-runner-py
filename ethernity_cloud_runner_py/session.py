"""Interactive session handle for the Ethernity Cloud runner.

Created by EthernityCloudRunner.run_session() / attach_session(). Wraps one
running session order and exposes the streaming API:

    session = runner.run_session(resources, enclave, version, code)
    seq = session.send_input("hello")          # etny-si row on chain, bytes through the storage
    for msg in session.wait_outputs(count=1):  # verified + decrypted etny-so
        print(msg["data"])
    final = session.close()                    # close row -> final result

Trust model, mirrored from the enclave side:
- inputs are transactions from THIS wallet (the contract only accepts the
  data owner), ciphertext encrypted for the trustedzone certificate, digest
  bound in the row;
- every output row's signature is verified against the task wallet the
  trustedzone attests in the session's 'etny-sw' row, signed with the key
  of the certificate the Image Registry holds for it (the certificate the
  challenge was sealed with) -- BEFORE the payload is decrypted or
  delivered, so the operator cannot forge or alter outputs;
- liveness (is_running / get_status) derives from chain state alone.
"""

import hashlib
import time
from typing import Any, Callable, Dict, List, Optional

from eth_account import Account
from eth_account.messages import encode_defunct

from .crypto import decrypt_nacl, encrypt, verify_certificate_signature

SESSION_INPUT_KEY = "etny-si"
SESSION_OUTPUT_KEY = "etny-so"
SESSION_WALLET_KEY = "etny-sw"
SESSION_WIRE_VERSION = "v1"
MAX_SESSION_MESSAGES = 256
# Mirror of the enclave's input-acceptance margin (M3): sending inside this
# window would only earn a signed 'late' notice, so refuse client-side.
SEND_CUTOFF_SECONDS = 600

SESSION_STATUS_NAMES = {
    0: "closed",
    1: "complete-at-timeout",
    2: "expired-idle",
    3: "expired-unprocessed",
    4: "flooded",
    5: "unsupported-securelock",
}

# Codes carried by 'error' output rows (msg["code"]): task codes for payload
# failures (5 = no ___etny_on_input___ handler defined, 1 = handler raised)
# and session notices 50-53 (malformed row, out-of-order seq, undecryptable
# input, securelock build without session support). 0 for ok/late rows.
SESSION_ERROR_CODE_NAMES = {
    1: "handler-error",
    5: "handler-not-defined",
    50: "input-malformed",
    51: "input-out-of-order",
    52: "input-undecryptable",
    53: "unsupported-securelock",
}


class SessionError(Exception):
    pass


class EthernityCloudSession:
    def __init__(self, runner, order_id: int):
        self.runner = runner
        self.order_id = int(order_id)
        # Retried: a replica of a load-balanced RPC that has not seen an order
        # placed moments ago reverts the read.
        order = runner.retry_operation(lambda: runner.protocol_contract.caller()._getOrder(self.order_id))
        self.do_req = int(order[2])
        self.dp_req = int(order[3])
        doreq = runner.protocol_contract.caller()._getDORequest(self.do_req)
        # _getDORequest: (downer, cpu, mem, storage, bandwidth, duration, ...)
        self.duration_hours = int(doreq[5]) if int(doreq[5]) < 1000 else int(doreq[5]) // 3600
        self.started_at = time.time()
        self.deadline = self.started_at + self.duration_hours * 3600
        self._rows_seen = 0
        self._input_seq = self._count_my_inputs()
        self.outputs: List[Dict[str, Any]] = []
        self.closed = False
        # The task wallet the trustedzone attested in the session's 'etny-sw'
        # row: the signer every output row is checked against. None until
        # that row has been read and verified.
        self._attested_wallet: Optional[str] = None

    # ----------------------------------------------------------------- helpers

    def _caller(self):
        return self.runner.protocol_contract.caller()

    def _count_my_inputs(self) -> int:
        """Resume seq from chain state so a reattached session continues
        exactly where the previous process stopped."""
        try:
            count = int(self._caller()._getMetadataCountForRequest(self.do_req))
        except Exception:
            return 0
        seq = 0
        for i in range(count):
            try:
                key, value = self._caller()._getMetadataValueForRequest(self.do_req, i)
            except Exception:
                break
            if key != SESSION_INPUT_KEY:
                continue
            parts = str(value or "").split(":")
            if len(parts) == 5 and parts[0] == SESSION_WIRE_VERSION:
                try:
                    if int(parts[2]) == self.order_id:
                        seq = max(seq, int(parts[1]) + 1)
                except ValueError:
                    continue
        return seq

    def _task_wallet(self) -> Optional[str]:
        """The task wallet the output rows are signed with: attested by the
        trustedzone in the session's 'etny-sw' row, signed with the key of
        the certificate the Image Registry holds for it. None until that
        row has been read and verified."""
        return self._attested_wallet

    def _accept_wallet_attestation(self, value: str) -> bool:
        """Verify an 'etny-sw' row, 'v1:<orderId>:<taskWallet>:<sigDerHex>',
        against the trustedzone's certificate (the one the challenge was
        sealed with) and keep its wallet. A row that does not verify is
        ignored: a node cannot name the signer of this session's outputs."""
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != SESSION_WIRE_VERSION:
            return False
        wallet, sig = parts[2], parts[3]
        try:
            if int(parts[1]) != self.order_id:
                return False
            signature = bytes.fromhex(sig[2:] if sig.startswith("0x") else sig)
        except ValueError:
            return False
        message = f"{SESSION_WALLET_KEY}|{self.order_id}|{wallet}".encode("utf-8")
        if not verify_certificate_signature(self.runner.enclave_public_key, message, signature):
            self.runner.logger.error(
                f"[session] task wallet attestation of {wallet} does not verify against the "
                f"trustedzone's certificate -- IGNORING")
            return False
        if self._attested_wallet is not None and self._attested_wallet.lower() != wallet.lower():
            self.runner.logger.error(
                f"[session] a second task wallet attestation ({wallet}) differs from the first "
                f"({self._attested_wallet}) -- IGNORING")
            return False
        self._attested_wallet = wallet
        self.runner.logger.info(f"[session] task wallet attested by the trustedzone: {wallet}")
        return True

    # ------------------------------------------------------------------ status

    def remaining_seconds(self) -> int:
        return max(0, int(self.deadline - time.time()))

    def is_running(self) -> bool:
        """Chain-state liveness: the order is still PROCESSING and inside its
        duration. No trust in the operator required."""
        if self.closed:
            return False
        try:
            status = int(self._caller()._getOrder(self.order_id)[4])
        except Exception:
            return False
        return status == 1 and time.time() < self.deadline

    def get_status(self) -> Dict[str, Any]:
        try:
            status = int(self._caller()._getOrder(self.order_id)[4])
        except Exception:
            status = -1
        acked = [o["ack"] for o in self.outputs if o.get("ack", -1) >= 0]
        return {
            "order_id": self.order_id,
            "running": status == 1 and time.time() < self.deadline,
            "order_status": status,
            "remaining_seconds": self.remaining_seconds(),
            "inputs_sent": self._input_seq,
            "last_acked_input": max(acked) if acked else -1,
            "outputs_received": len(self.outputs),
        }

    # ------------------------------------------------------------------- input

    def send_input(self, data: str) -> int:
        """Encrypt for the enclave, hand the bytes to the configured storage
        (the bootnode's payload intake by default), commit the etny-si row.
        Returns the input seq. Refuses when the session cannot answer any
        more (cap reached or inside the enclave's input cutoff)."""
        if self.closed:
            raise SessionError("session is closed")
        if self._input_seq >= MAX_SESSION_MESSAGES:
            raise SessionError(f"session input cap reached ({MAX_SESSION_MESSAGES})")
        if self.remaining_seconds() <= SEND_CUTOFF_SECONDS:
            raise SessionError(
                "session is inside its shutdown window -- the enclave would "
                "only answer with a timeout notice; not sending")
        if not self.is_running():
            raise SessionError("session order is no longer processing")
        ciphertext = encrypt(str(data).encode("utf-8"), self.runner.enclave_public_key)
        cid = self.runner.storage().upload_to_ipfs(ciphertext)
        if not cid:
            raise SessionError("the configured storage did not accept the input")
        digest = hashlib.sha256(
            ciphertext if isinstance(ciphertext, bytes) else str(ciphertext).encode("utf-8")
        ).hexdigest()
        value = f"{SESSION_WIRE_VERSION}:{self._input_seq}:{self.order_id}:{cid}:{digest}"
        tx_hash = self.runner.contract.add_metadata_to_request(
            self.do_req, SESSION_INPUT_KEY, value)
        receipt = self.runner.poll_transaction(tx_hash, max_attempts=60)
        if not receipt or receipt["status"] != 1:
            raise SessionError(f"input row transaction failed ({tx_hash})")
        # With the public intake, the row is on chain now, so the bytes it
        # names can be delivered.
        self.runner.storage().flush_pending(self.do_req)
        seq = self._input_seq
        self._input_seq += 1
        self.runner.logger.info(f"[session] input {seq} committed ({cid})")
        return seq

    # ------------------------------------------------------------------ output

    def poll_outputs(self) -> List[Dict[str, Any]]:
        """Read new rows: the 'etny-sw' row attests the task wallet, each
        'etny-so' row is verified against it, its payload fetched, verified
        and decrypted. Returns only the NEW verified messages (also appended
        to self.outputs). An output row before any attestation is discarded:
        its signer cannot be checked."""
        try:
            count = int(self._caller()._getMetadataCountForDPRequest(self.dp_req))
        except Exception as e:
            self.runner.logger.debug(f"[session] output count read failed: {e}")
            return []
        fresh = []
        while self._rows_seen < count:
            i = self._rows_seen
            try:
                key, value = self._caller()._getMetadataValueForDPRequest(self.dp_req, i)
            except Exception:
                break
            if key == SESSION_WALLET_KEY:
                self._accept_wallet_attestation(str(value or ""))
                self._rows_seen = i + 1
                continue
            if key != SESSION_OUTPUT_KEY:
                self._rows_seen = i + 1
                continue
            self._rows_seen = i + 1
            if self._attested_wallet is None:
                self.runner.logger.error(
                    f"[session] output row {i} precedes the task wallet attestation; its signer "
                    f"cannot be checked -- DISCARDING")
                continue
            msg = self._verify_output_row(str(value or ""))
            if msg is not None:
                self.outputs.append(msg)
                fresh.append(msg)
        return fresh

    def _verify_output_row(self, value: str) -> Optional[Dict[str, Any]]:
        parts = value.split(":")
        if len(parts) != 9 or parts[0] != SESSION_WIRE_VERSION:
            return None
        try:
            seq, row_order, ack = int(parts[1]), int(parts[2]), int(parts[3])
            code = int(parts[5])
        except ValueError:
            return None
        status, cid, sha_hex, sig = parts[4], parts[6], parts[7].lower(), parts[8]
        if row_order != self.order_id:
            return None
        message = f"etny-so|{self.order_id}|{seq}|{ack}|{status}|{code}|{cid}|{sha_hex}"
        try:
            signer = Account.recover_message(
                encode_defunct(text=message),
                signature=bytes.fromhex(sig[2:] if sig.startswith("0x") else sig))
        except Exception as e:
            self.runner.logger.warning(f"[session] output {seq}: bad signature encoding ({e})")
            return None
        task_wallet = self._task_wallet()
        if task_wallet is None or signer.lower() != task_wallet.lower():
            self.runner.logger.error(
                f"[session] output {seq}: signature by {signer}, expected the "
                f"attested task wallet {task_wallet} -- DISCARDING (operator forgery?)")
            return None
        msg = {"seq": seq, "ack": ack, "status": status, "code": code, "data": None}
        if not cid:
            return msg  # signed notice row without payload (late)
        # 'ok' rows carry the reply; 'error' rows carry an encrypted
        # explanation of why the input was not processed -- fetch both.
        try:
            content = self.runner.storage().get_file_content(cid)
            raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
            if hashlib.sha256(raw).hexdigest() != sha_hex:
                self.runner.logger.error(
                    f"[session] output {seq}: content does not match the signed digest -- DISCARDING")
                return None
            decrypted = decrypt_nacl(self.runner.private_key,
                                     raw.decode("utf-8") if isinstance(raw, bytes) else raw)
            if not decrypted.get("success"):
                self.runner.logger.error(f"[session] output {seq}: could not decrypt")
                return None
            msg["data"] = decrypted["data"]
        except Exception as e:
            self.runner.logger.warning(f"[session] output {seq}: payload not readable yet ({e})")
            return None
        return msg

    def wait_outputs(self, count: int = 1, timeout: int = 300,
                     poll_seconds: int = 5) -> List[Dict[str, Any]]:
        """Block until `count` new verified outputs arrive (or timeout)."""
        collected: List[Dict[str, Any]] = []
        deadline = time.time() + timeout
        while time.time() < deadline and len(collected) < count:
            collected.extend(self.poll_outputs())
            if len(collected) >= count:
                break
            time.sleep(poll_seconds)
        return collected

    def on_output(self, callback: Callable[[Dict[str, Any]], None],
                  poll_seconds: int = 5) -> None:
        """Poll in a background thread, invoking callback per verified
        message, until the session leaves PROCESSING."""
        import threading

        def loop():
            while self.is_running():
                for msg in self.poll_outputs():
                    try:
                        callback(msg)
                    except Exception as e:
                        self.runner.logger.error(f"[session] output callback failed: {e}")
                time.sleep(poll_seconds)

        threading.Thread(target=loop, daemon=True).start()

    # ------------------------------------------------------------------- close

    def close(self, wait: bool = True, timeout: int = 900) -> Optional[Dict[str, Any]]:
        """Commit the close row; optionally wait for the order to settle and
        return the final task result (the session summary)."""
        if not self.closed:
            value = f"{SESSION_WIRE_VERSION}:close:{self.order_id}"
            tx_hash = self.runner.contract.add_metadata_to_request(
                self.do_req, SESSION_INPUT_KEY, value)
            self.runner.poll_transaction(tx_hash, max_attempts=60)
            self.closed = True
            self.runner.logger.info(f"[session] close requested for order {self.order_id}")
        if not wait:
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                status = int(self._caller()._getOrder(self.order_id)[4])
                if status != 1:
                    break
            except Exception:
                pass
            self.poll_outputs()
            time.sleep(5)
        # Final drain, then the ordinary result path (summary + transcript).
        self.poll_outputs()
        try:
            return self.runner.get_result_from_order(self.order_id)
        except Exception as e:
            self.runner.logger.warning(f"[session] final result not readable: {e}")
            return None
