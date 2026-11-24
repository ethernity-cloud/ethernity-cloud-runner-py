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

A handle works through what the runner held when it was made, whatever the
runner holds later: its rows and its close row go through that protocol
contract (its network, its PoX and its signer), its reads are made on it,
its inputs are sealed for, and the task wallet attestation is checked
against, the trustedzone certificate of that time, and its signatures and
decryptions use the wallet key of that time. The runner's close() detaches
the handle: from then on it sends and reads nothing, and send_input,
poll_outputs, the waits and close raise SessionError. A close(wait=True)
that has returned the session's summary takes the handle out of the
runner's handles.
"""

import hashlib
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from eth_account import Account
from eth_account.messages import encode_defunct

from .crypto import decrypt_nacl, encrypt, statement_bytes, verify_certificate_signature
from .ipfs import INTAKE_NOT_NAMED, owner_signature_message
from .rpc import read_again

SESSION_INPUT_KEY = "etny-si"
SESSION_OUTPUT_KEY = "etny-so"
SESSION_WALLET_KEY = "etny-sw"
SESSION_WIRE_VERSION = "v1"

# The grammar of a session's etny-si rows (spec/matching.md section 20,
# SF20), which both trustedzones and the validators' members read:
#   input-row = "v1" ":" seq ":" orderId ":" cid ":" sha256   (five fields)
#   close-row = "v1" ":" "close" ":" orderId [ ":" depth ]
# seq and orderId plain decimal ("0", or a digit 1-9 and digits) of at most
# 2^64 - 1, depth one to nine digits, cid and sha256 any text but ":"; a row
# is read as its bytes stand.
UINT64_MAX = 2**64 - 1
_PLAIN_DECIMAL = re.compile(r"0|[1-9][0-9]*")
_DEPTH = re.compile(r"[0-9]{1,9}")


def _plain(text: str) -> Optional[int]:
    if not _PLAIN_DECIMAL.fullmatch(text):
        return None
    value = int(text)
    return value if value <= UINT64_MAX else None


def session_row(value: str, order_id: int) -> Optional[Tuple[str, Optional[int]]]:
    """An etny-si row of order `order_id` read by the grammar of section 20:
    ("input", seq), ("close", depth) with depth None when the row states
    none, or None for a row outside the grammar or naming another order."""
    parts = str(value).split(":")
    if len(parts) < 3 or parts[0] != SESSION_WIRE_VERSION:
        return None
    if parts[1] == "close":
        if len(parts) > 4 or _plain(parts[2]) != order_id:
            return None
        if len(parts) == 3:
            return ("close", None)
        return ("close", int(parts[3])) if _DEPTH.fullmatch(parts[3]) else None
    if len(parts) != 5:
        return None
    seq = _plain(parts[1])
    if seq is None or _plain(parts[2]) != order_id:
        return None
    return ("input", seq)


def next_input_seq(values: Iterable[str], order_id: int) -> int:
    """The seq an input row of order `order_id` takes after the etny-si rows
    `values`, in the request's order: the next one the enclave expects (from
    0), every row outside the grammar, of another order, a gap or a
    duplicate skipped, as the trustedzones and the members read them."""
    expected = 0
    for value in values:
        row = session_row(value, order_id)
        if row is not None and row[0] == "input" and row[1] == expected:
            expected += 1
    return expected


def input_row(seq: int, order_id: int, cid: str, digest: str) -> str:
    """The etny-si input row `v1:<seq>:<orderId>:<cid>:<digest>`. Raises
    ValueError for a value the grammar of section 20 refuses: a seq or an
    order id that is not a whole number of 0 to 2^64 - 1, a cid or a digest
    holding ":"."""
    for name, number in (("seq", seq), ("order id", order_id)):
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= UINT64_MAX:
            raise ValueError(f"an etny-si row's {name} is a whole number of 0 to 2^64 - 1, not {number!r}")
    for name, text in (("cid", cid), ("digest", digest)):
        if ":" in str(text):
            raise ValueError(f"an etny-si row's {name} holds no ':', not {text!r}")
    return f"{SESSION_WIRE_VERSION}:{seq}:{order_id}:{cid}:{digest}"


def close_row(order_id: int) -> str:
    """The etny-si close row `v1:close:<orderId>`, which states no depth.
    Raises ValueError for an order id that is not a whole number of 0 to
    2^64 - 1."""
    if isinstance(order_id, bool) or not isinstance(order_id, int) or not 0 <= order_id <= UINT64_MAX:
        raise ValueError(f"an etny-si row's order id is a whole number of 0 to 2^64 - 1, not {order_id!r}")
    return f"{SESSION_WIRE_VERSION}:close:{order_id}"
# An output row whose payload no endpoint serves yet, or serves under its CID
# with other bytes, is read again on later polls for this long before it is
# given up: the node pins the payload in the background and the gateway may
# lag the row.
PAYLOAD_RETRY_SECONDS = 600
# _verify_output_row's answer for such a row.
PAYLOAD_PENDING = object()
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
    6: "transferred",
    7: "transfer-forced",
}

# Codes carried by 'error' output rows (msg["code"]): task codes for payload
# failures (5 = no ___etny_on_input___ handler defined, 1 = handler raised)
# and session notices 50-54 (malformed row, out-of-order seq, undecryptable
# input, securelock build without session support, a predecessor's cut input
# the successor could not replay). 0 for ok/late rows.
SESSION_ERROR_CODE_NAMES = {
    1: "handler-error",
    5: "handler-not-defined",
    50: "input-malformed",
    51: "input-out-of-order",
    52: "input-undecryptable",
    53: "unsupported-securelock",
    54: "session-replay-unavailable",
}


class SessionError(Exception):
    pass


class EthernityCloudSession:
    def __init__(self, runner, order_id: int, challenge: Optional[bytes] = None,
                 request: Optional[Dict[str, Any]] = None):
        """The handle of session order `order_id` of `runner`. `challenge` is
        the challenge of the session's request and `request` the result
        fields of that request (EthernityCloudRunner._request_fields), which
        run_session() knows and attach_session() does not. close(wait=True)
        checks the summary's signer against the challenge when given, else
        against the task wallet the trustedzone attested, and the summary
        carries `request`'s fields, None for those not given."""
        self.runner = runner
        self.order_id = int(order_id)
        self._challenge = challenge
        self._request = dict(request or {})
        # What the runner holds as the handle is made, kept for the handle's
        # life: the protocol contract its rows go through (a network, a PoX
        # and a signer), the web3 contract its reads are made on, the
        # trustedzone's certificate and the wallet key.
        self._contract = runner.contract
        self._protocol_contract = runner.protocol_contract
        self._certificate = runner.enclave_public_key
        self._private_key = runner.private_key
        # Whether the network's pricing names a PoxMatching, where an etny-sw
        # row verifies only in the statement form (_statement_only); read
        # once, at the first etny-sw row. The runner takes no set_network()
        # while it holds the handle.
        self._matching_network: Optional[bool] = None
        # The message of the SessionError the handle raises once the runner's
        # close() has detached it (_detach); None while it serves.
        self._detached: Optional[str] = None
        # The key under which the handle's inputs are queued for the intake
        # (IPFSClient.upload_to_ipfs): a task or another handle of the runner
        # posts and drops none of them.
        self._blobs = object()
        # The summary close(wait=True) returned, once it has (_summarized):
        # the handle is then out of the runner's handles.
        self._summary: Optional[Dict[str, Any]] = None
        self._summarized = False
        # Retried: a replica of a load-balanced RPC that has not seen an order
        # placed moments ago reverts the read.
        order = runner.retry_operation(lambda: self._protocol_contract.caller()._getOrder(self.order_id))
        # The order's struct, which close(wait=True) reads the result with.
        self._order = order
        self.do_req = int(order[2])
        self.dp_req = int(order[3])
        doreq = self._read(lambda: self._protocol_contract.caller()._getDORequest(self.do_req))
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
        # Row index -> when its payload was first found not readable; the row
        # is retried until PAYLOAD_RETRY_SECONDS after that.
        self._payload_waits: Dict[int, float] = {}
        # The owner's signature that lodges this session's inputs with the
        # intake before their rows (_lodge_input); signed once, at the first.
        self._owner_signature: Optional[str] = None
        # Held by poll_outputs: one thread at a time reads the rows, so a row
        # is taken, and its message delivered, once.
        self._poll_lock = threading.Lock()

    # ----------------------------------------------------------------- helpers

    def _detach(self, reason: str) -> None:
        """Ends the handle's work; the runner's close() calls it. `reason` is
        the message of the SessionError that send_input, poll_outputs, the
        waits and close raise from then on; is_running answers False and
        get_status an order_status of -1. The wallet key is dropped."""
        self._detached = reason
        self._private_key = ""

    def _attached(self) -> bool:
        return self._detached is None

    def _require_attached(self) -> None:
        """Raises SessionError on a handle the runner's close() detached."""
        if self._detached is not None:
            raise SessionError(self._detached)

    def _caller(self):
        """The read interface of the contract the handle was made with."""
        self._require_attached()
        return self._protocol_contract.caller()

    @staticmethod
    def _read(read: Callable[[], Any]) -> Any:
        """`read()`, made again while the RPC does not serve it
        (rpc.read_again); the last such error, and any other error at once,
        is raised."""
        return read_again(read)

    def _count_my_inputs(self) -> int:
        """Resume seq from chain state so a reattached session continues
        exactly where the previous process stopped: the seq the enclave
        expects after the request's etny-si rows read so far
        (next_input_seq)."""
        try:
            count = int(self._read(lambda: self._caller()._getMetadataCountForRequest(self.do_req)))
        except Exception:
            return 0
        values = []
        for i in range(count):
            try:
                key, value = self._read(lambda: self._caller()._getMetadataValueForRequest(self.do_req, i))
            except Exception:
                break
            if key == SESSION_INPUT_KEY:
                values.append(str(value or ""))
        return next_input_seq(values, self.order_id)

    def _task_wallet(self) -> Optional[str]:
        """The task wallet the output rows are signed with: attested by the
        trustedzone in the session's 'etny-sw' row, signed with the key of
        the certificate the Image Registry holds for it. None until that
        row has been read and verified."""
        return self._attested_wallet

    def _statement_only(self) -> bool:
        """Whether an etny-sw row verifies only in the statement form: on a
        network whose pricing names a PoxMatching
        (EthernityCloudRunner._names_pox_matching), read once per handle."""
        if self._matching_network is None:
            self._matching_network = bool(self.runner._names_pox_matching())
        return self._matching_network

    def _accept_wallet_attestation(self, value: str) -> bool:
        """Verify an 'etny-sw' row, 'v1:<orderId>:<taskWallet>:<sigDerHex>',
        against the trustedzone's certificate (the one the challenge was
        sealed with) and keep its wallet. The signature is over the statement
        etny-sw|<orderId>|<taskWallet> in the statement form
        (crypto.statement_bytes); on a network whose pricing names no
        PoxMatching also over its UTF-8 bytes, the plain form of the
        trustedzones built before the statement form (spec/matching.md 3.7,
        reserved-prefixes.json cutRule; OD10 B). A row that does not verify
        is ignored: a node cannot name the signer of this session's
        outputs."""
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
        statement = f"{SESSION_WALLET_KEY}|{self.order_id}|{wallet}"
        forms = [statement_bytes(statement)]
        if not self._statement_only():
            forms.append(statement.encode("utf-8"))
        if not any(verify_certificate_signature(self._certificate, form, signature) for form in forms):
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
        duration. No trust in the operator required. The order's read is
        made again while the RPC does not answer it (_read); a read that
        fails after that answers False."""
        if self.closed:
            return False
        try:
            status = int(self._read(lambda: self._caller()._getOrder(self.order_id))[4])
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
        more (cap reached or inside the enclave's input cutoff). The input is
        sealed for the certificate, and its row sent through the contract,
        the handle was made with. Through an intake its bytes are queued
        under the handle's key (_blobs), which no task and no other handle of
        the runner delivers or drops. An input whose row was not sent, or was
        mined as reverted, leaves no blob in the intake's queue
        (IPFSClient.drop_pending): no row names it, and the intake refuses
        it when a later input's delivery posts the handle's queue."""
        self._require_attached()
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
        storage = self.runner.storage()
        # The input sealed for the enclave, its CID and digest through the
        # configured storage; _seal_artefact raises when the storage does not
        # take it, before any transaction.
        cid, digest = self.runner._seal_artefact(str(data).encode("utf-8"), self._certificate, self._blobs)
        if not cid:
            raise SessionError("the configured storage did not accept the input")
        row_sent = False
        try:
            # The bytes reach the intake before the row that names them,
            # under the owner's signature; an input is complete only once its
            # row is on chain, so a client that stops before that leaves no
            # row without bytes.
            self._lodge_input(cid)
            value = input_row(self._input_seq, self.order_id, cid, digest)
            tx_hash = self._contract.add_metadata_to_request(self.do_req, SESSION_INPUT_KEY, value)
            row_sent = True
            receipt = self.runner._poll_receipt(self._contract.get_provider().eth, tx_hash, 60, self._attached)
            if receipt and receipt["status"] != 1:
                row_sent = False
            if not receipt or receipt["status"] != 1:
                raise SessionError(f"input row transaction failed ({tx_hash})")
        finally:
            if not row_sent:
                storage.drop_pending(self._blobs, [cid])
        # With the public intake, the row is on chain now, so bytes it names
        # that were not lodged before it can be delivered, with those of an
        # earlier input of the handle whose row had no receipt then; nothing
        # is queued when they were lodged.
        storage.flush_pending(self.do_req, operation=self._blobs)
        # An input the held cache carried is referenced on chain now.
        storage.release_held([cid])
        seq = self._input_seq
        self._input_seq += 1
        self.runner.logger.info(f"[session] input {seq} committed ({cid})")
        return seq

    def _lodge_input(self, cid: str) -> bool:
        """Lodge input `cid`'s queued bytes with the intake before the row
        that names them, under the request owner's signature, made once per
        session from the handle's wallet key. True when the intake took them.
        False when the bytes are to go after the row instead: no intake, no
        key, or an intake without the signed path (its 403 INTAKE_NOT_NAMED).
        Raises SessionError when the intake refused the lodged bytes
        otherwise, or could not be reached: the row is not committed without
        its bytes in place, and the input can be sent again."""
        storage = self.runner.storage()
        if not getattr(storage, "intake_url", "") or not self._private_key:
            return False
        if self._owner_signature is None:
            message = owner_signature_message(storage.network, self.do_req)
            self._owner_signature = Account.sign_message(
                encode_defunct(text=message), private_key=self._private_key).signature.hex()
        delivered, refused = storage.deliver_signed(self.do_req, self._owner_signature, [cid],
                                                    operation=self._blobs)
        if cid in delivered:
            return True
        if INTAKE_NOT_NAMED in str(refused.get(cid, "")):
            self.runner.logger.warning(f"[session] input {self._input_seq}: the intake takes no lodged bytes; "
                                       f"delivered after its row")
            return False
        raise SessionError(f"input {self._input_seq} was not lodged with the intake ({refused.get(cid)}); "
                           f"not committed, send it again")

    # ------------------------------------------------------------------ output

    def poll_outputs(self) -> List[Dict[str, Any]]:
        """Read new rows: the 'etny-sw' row attests the task wallet, each
        'etny-so' row is verified against it, its payload fetched, verified
        and decrypted. Returns only the NEW verified messages (also appended
        to self.outputs). An output row before any attestation is discarded:
        its signer cannot be checked. A verified row whose payload is not
        readable yet is kept, and the rows after it with it, for the next
        poll, up to PAYLOAD_RETRY_SECONDS. One thread at a time reads the rows
        (_poll_lock), so on_output, wait_output, wait_outputs and close of
        other threads take each message once. SessionError on a handle the
        runner's close() detached."""
        self._require_attached()
        with self._poll_lock:
            return self._poll_rows()

    def _poll_rows(self) -> List[Dict[str, Any]]:
        """poll_outputs' read of the new rows, under its lock."""
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
                try:
                    self._statement_only()
                except Exception as e:
                    self.runner.logger.debug(f"[session] the network's PoxMatching read failed: {e}; the etny-sw "
                                             "row is read again at the next poll")
                    break
                self._accept_wallet_attestation(str(value or ""))
                self._rows_seen = i + 1
                continue
            if key != SESSION_OUTPUT_KEY:
                self._rows_seen = i + 1
                continue
            if self._attested_wallet is None:
                self._rows_seen = i + 1
                self.runner.logger.error(
                    f"[session] output row {i} precedes the task wallet attestation; its signer "
                    f"cannot be checked -- DISCARDING")
                continue
            msg = self._verify_output_row(str(value or ""))
            if msg is PAYLOAD_PENDING:
                waited = time.time() - self._payload_waits.setdefault(i, time.time())
                if waited < PAYLOAD_RETRY_SECONDS:
                    break
                self.runner.logger.error(
                    f"[session] output row {i}: payload not readable in {int(waited)} s -- DISCARDING")
                msg = None
            self._rows_seen = i + 1
            self._payload_waits.pop(i, None)
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
            raw = self._fetch_payload(cid)
        except Exception as e:
            self.runner.logger.warning(f"[session] output {seq}: payload not readable yet ({e})")
            return PAYLOAD_PENDING
        if raw is None or hashlib.sha256(raw).hexdigest() != sha_hex:
            self.runner.logger.warning(
                f"[session] output {seq}: payload not served under its CID yet; retrying")
            return PAYLOAD_PENDING
        decrypted = decrypt_nacl(self._private_key, raw.decode("utf-8"))
        if not decrypted.get("success"):
            self.runner.logger.error(f"[session] output {seq}: could not decrypt -- DISCARDING")
            return None
        msg["data"] = decrypted["data"]
        return msg

    def _fetch_payload(self, cid: str) -> Optional[bytes]:
        """The bytes an output row's CID names, or None when no endpoint
        served them."""
        content = self.runner.storage().get_file_content(cid)
        if content is None:
            return None
        return content if isinstance(content, bytes) else str(content).encode("utf-8")

    def wait_output(self, seq: int, timeout: int = 300,
                    poll_seconds: int = 5) -> Optional[Dict[str, Any]]:
        """The verified output answering input `seq` (the row whose ack is
        `seq`: an 'ok' reply, or an 'error' or 'late' notice), polled for
        until it arrives or `timeout` seconds pass; None then. Outputs
        answering other inputs that arrive meanwhile stay in self.outputs.
        This is the wait for a request-reply exchange; wait_outputs returns
        any new output, so there a late answer to an earlier input would be
        taken for the current one's."""
        def answer():
            return next((m for m in self.outputs if m["ack"] == seq), None)

        deadline = time.time() + timeout
        while answer() is None and time.time() < deadline:
            self.poll_outputs()
            if answer() is None:
                time.sleep(poll_seconds)
        return answer()

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
        message, until the session leaves PROCESSING or the runner's close()
        detaches the handle."""
        import threading

        def loop():
            while self.is_running():
                try:
                    fresh = self.poll_outputs()
                except SessionError:
                    return
                for msg in fresh:
                    try:
                        callback(msg)
                    except Exception as e:
                        self.runner.logger.error(f"[session] output callback failed: {e}")
                time.sleep(poll_seconds)

        threading.Thread(target=loop, daemon=True).start()

    # ------------------------------------------------------------------- close

    def close(self, wait: bool = True, timeout: int = 900) -> Optional[Dict[str, Any]]:
        """Commit the close row; optionally wait for the order to settle and
        return the final task result (the session summary). The row goes
        through the contract the handle was made with. The summary is read
        with the handle's own order, its duration, its request's fields and
        its challenge (EthernityCloudRunner.get_result_from_order). A handle
        without the challenge, which attach_session() makes, checks the
        result's signer against the task wallet the trustedzone attested in
        the session's etny-sw row: a result another wallet signed gives no
        summary, and neither does a handle that has verified no
        attestation. SessionError on a
        handle the runner's close() detached, before the row and during the
        wait: nothing is sent. Once a close(wait=True) has returned the
        summary, the handle is out of the runner's handles
        (EthernityCloudRunner._release_session) and the runner is in
        progress no more for it, so it takes set_network(),
        set_private_key() and run() again; a later close(wait=True) of the
        handle returns that summary and reads nothing. After
        close(wait=False) the runner keeps the handle: a close(wait=True)
        made later reads the summary through it."""
        self._require_attached()
        if self._summarized:
            return self._summary if wait else None
        if not self.closed:
            value = close_row(self.order_id)
            tx_hash = self._contract.add_metadata_to_request(self.do_req, SESSION_INPUT_KEY, value)
            self.runner._poll_receipt(self._contract.get_provider().eth, tx_hash, 60, self._attached)
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
        # Final drain, then the ordinary result path (summary + transcript),
        # with the handle's own order, request and challenge, and the task
        # wallet the drain may have attested.
        self.poll_outputs()
        try:
            summary = self.runner.get_result_from_order(
                self.order_id, order=self._order, challenge=self._challenge, signer=self._attested_wallet,
                request=dict(self._request, duration_hours=self.duration_hours))
        except Exception as e:
            self.runner.logger.warning(f"[session] final result not readable: {e}")
            summary = None
        self._summary, self._summarized = summary, True
        self.runner._release_session(self)
        return summary
