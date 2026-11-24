<p align="center">
  <a href="https://ethernity.cloud" title="Ethernity Cloud">
    <img src="https://ethernity.cloud/images/dark_gradient_logo.svg" alt="Ethernity Cloud logo" width="244" />
  </a>
</p>

<h3 align="center">The Python implementation of the Ethernity CLOUD runner protocol</h3>

### Installation

To begin developing with the Ethernity Cloud Runner, you need to set up your environment:

```console
$ python -m 'venv' venv
$ source venv/bin/activate
$ pip install ethernity-cloud-runner-py
```

This command will install the necessary dependencies for the Ethernity Cloud Runner package. With the packages installed, you're ready to start utilizing the Ethernity Cloud Runner functionality and explore its capabilities for your application development.

### Environment Prerequisites

#### 1. IDE

For a streamlined development process, we recommend using Visual Studio Code—a powerful and versatile code editor that offers a seamless experience for developers. You can download Visual Studio Code from the official [website](https://code.visualstudio.com/).

After running the IDE, a new workspace will be created, where you can start developing the framework and code.

#### 2. Python

Ensure you have Python installed on your local machine. You can download Python from the official [website](https://www.python.org/downloads/).

#### 3. Wallet Setup

A wallet is a crucial tool within the Ethernity Cloud ecosystem, empowering users to securely store and transfer their data for processing. As a developer, having a Web3 dApp testing wallet is necessary.

The wallet setup process with Metamask is detailed here: [Getting started with MetaMask](https://support.metamask.io/hc/en-us/articles/360015489531-Getting-started-with-MetaMask).

Ethernity Cloud runs on several networks; set up your wallet for the one you intend to use: Bloxberg (mainnet and testnet), Polygon (mainnet) and Polygon Amoy, IoTeX Testnet, Ethereum Sepolia, and LitVM LiteForge.

A testnet that has an ethernity-cas validator set -- the bloxberg testnet and LitVM LiteForge -- comes in two kinds. `EthernityCloudRunner("BLOXBERG", "TESTNET")` and `("LITVM", "LITEFORGE")` run the securelock in an enclave the set attests, on nodes whose platform it can attest (DCAP), and the set validates the order in full, as on mainnet. `("BLOXBERG", "TESTNET_UNSAFE")` and `("LITVM", "LITEFORGE_UNSAFE")` are the `-unsafe` networks beside them: the same chain and contracts, for hardware SGX platforms the CAS cannot attest (EPID-only, SGX1); their enclaves are debug-signed and self-signed from their measurement, so a result proves which image ran, not that an enclave ran it, and the validators judge such an order without the challenge-derived signer check. The securelock and trustedzone of an `-unsafe` network carry `-unsafe` in their registered names (see "Choosing the trustedzone"). Mainnet has no `-unsafe` network.

The bloxberg testnet and Polygon Amoy each also hold a PoX 1.0 network, a copy of its mainnet's PoX 1.0 contracts: `EthernityCloudRunner("BLOXBERG", "TESTNET_POX10")` and `EthernityCloudRunner("POLYGON", "AMOY_POX10")` (see "The testnet PoX 1.0 networks").

### 4. Code execution

To execute a new task using the Ethernity Cloud Runner, follow the template provided below. Insert your code into the designated section; the runner delivers the task's artefacts, submits the task on chain and verifies the result.

```python
# ethernity_task.py
import os
import time

from dotenv import load_dotenv

from ethernity_cloud_runner_py.runner import EthernityCloudRunner  # type: ignore


def execute_task() -> None:
    load_dotenv()
    code = '___etny_result___("Hello, Python World!")'

    runner = EthernityCloudRunner("BLOXBERG", "TESTNET")
    runner.set_private_key(os.environ["PRIVATE_KEY"])
    # The task's artefacts go through the bootnode's payload intake unless
    # runner.set_storage_ipfs(url, token) names a Kubo RPC API of your own.
    runner.connect()

    resources = {
        "taskPrice": 8,
        "cpu": 1,
        "memory": 1,
        "storage": 1,
        "bandwidth": 1,
        "duration": 1,
        "validators": 1,
    }
    # run(resources, securelock, version, code): the securelock is the name
    # ecld-publish registered your dApp's enclave under, and "v3" the protocol
    # version the image registry lists it under. run() returns at once and the
    # task proceeds on a thread of its own.
    runner.run(resources, "my-dapp-securelock", "v3", code)

    while runner.is_running():
        time.sleep(1)
    state = runner.get_state()
    if state["status"] == "SUCCESS":
        print(runner.get_result()["value"])
    else:
        print(f"Error: {state['last_error']}")


if __name__ == "__main__":
    execute_task()

```

Save the above script as `ethernity_task.py` and run it from the command line:

```sh
$ python ethernity_task.py
```

make sure to have .env file with the following content (the key is 64 hex digits, prefixed with `0x`):

```sh
PRIVATE_KEY=0x42....
```
Without it the script will not be able to make blockchain transactions.

This script connects the runner with the wallet's key, submits the task and polls its state until it finishes; the result or the error is printed to the console.

### Choosing the trustedzone

`run()` and `run_session()` take `trustedzone_enclave`, the trustedzone the securelock was built against. It defaults to the network's (`etny-pynithy-testnet` on the bloxberg testnet, a trustedzone the chain's ethernity-cas validator set provisions); a nodenithy dApp passes `etny-nodenithy-testnet`.

A securelock published without a CAS (`<project>-unsafe`) runs on an `-unsafe` network, which you choose by name: `EthernityCloudRunner("BLOXBERG", "TESTNET_UNSAFE")` or `EthernityCloudRunner("LITVM", "LITEFORGE_UNSAFE")`. An `-unsafe` network has the chain and contracts of the network it is named after; its trustedzone is `etny-pynithy-testnet-unsafe` (`ecld-pynithy-litvm-testnet-unsafe` on LitVM), and a nodenithy dApp passes the `etny-nodenithy-...-unsafe` one. The runner runs an `-unsafe` trustedzone only on an `-unsafe` network and runs nothing else there, so a task that runs without a CAS always says so in the network it names.

### The testnet PoX 1.0 networks

Two testnet networks run the PoX 1.0 contracts of the mainnets, beside the PoX 2.0 networks of the same chains (`("BLOXBERG", "TESTNET")`, `("POLYGON", "AMOY")`). The runner uses each as it uses the mainnet it copies.

| | `EthernityCloudRunner("BLOXBERG", "TESTNET_POX10")` | `EthernityCloudRunner("POLYGON", "AMOY_POX10")` |
|---|---|---|
| Network | `bloxberg_testnet_pox10`, a copy of the bloxberg mainnet's contracts | `polygon_amoy_pox10`, a copy of Polygon mainnet's contracts |
| Chain | 8995, `https://bloxberg.ethernity.cloud` | 80002, `https://polygon-amoy-bor-rpc.publicnode.com` |
| PoX | `0x69A7bEB5Da2d3dA711d52E491D71e51296b08745` | `0x9Aad82557c84c11C4031382d8Bf2cacF8f256a02` |
| Token | the PoX itself: tE10 ("PoX10 Test ETNY") | tECLD `0x9927809B61122B2af3f3b3A3303875e0687b8eE3`, the token of `("POLYGON", "AMOY")` |
| Image registry | `0x7dBC1b591cc3b7136D863bc7430C6Db50E929665` | `0xa2EE2a9118d0011AF05a6196c862D37d8c29F8eC` |
| Trustedzones | `etny-pynithy-testnet-pox10`; a nodenithy dApp passes `etny-nodenithy-testnet-pox10` | `ecld-pynithy-amoy-pox10`; a nodenithy dApp passes `ecld-nodenithy-amoy-pox10` |
| Token approval | none: the PoX holds the balances | the PoX is approved for the request's escrow |
| A wallet below the escrow | the task fails at `INIT`, before any transaction | while it holds less than 100 tECLD it draws the token's `faucet()`, which gives 1000 tECLD to such a wallet; from 100 tECLD the task fails at `INIT`, before any transaction |
| Fees | the fixed gas price of the bloxberg networks | EIP-1559, default ceiling 500 gwei, which admits a base fee up to 425.45 gwei |
| Enclave State Registry | `0x0Ea1728EAE108FD3B9340ae91451348E2Cc6b4E4`, the bloxberg testnet's | none |

The tE10 token has no faucet and no mint: it reaches a wallet by a transfer from a wallet that holds it. A run from a wallet that holds less than the request's escrow (`taskPrice * validators * duration`) ends in `ERROR` with:

```
Insufficient wallet balance. Required: 30, Available: 29. The token tE10 (0x69A7bEB5Da2d3dA711d52E491D71e51296b08745) of BLOXBERG TESTNET_POX10 has no faucet: the wallet 0x1111111111111111111111111111111111111111 needs a transfer of 1 tE10 or more before the request.
```

`run_session()` raises the same message as a `ValueError`. On `("POLYGON", "AMOY_POX10")` a wallet that holds 100 tECLD or more and less than the escrow is refused the same way, with `has a faucet that gives to a wallet holding less than 100 tECLD` in place of `has no faucet`. `("POLYGON", "AMOY")` and `("POLYGON", "AMOY_UNSAFE")`, whose token is the same tECLD, follow the same rule: below the escrow a wallet draws the faucet while it holds less than 100 tECLD and is refused from 100 tECLD, naming its own network.

Each of the two networks runs its two trustedzones and no other, and they run on no other network: `run()` and `run_session()` raise `ValueError` before any read or transaction for a trustedzone of the table above on another network (`ecld-pynithy-amoy-pox10 is a trustedzone of the POLYGON AMOY_POX10 network and runs on no other: run it there, not on POLYGON AMOY`) and for any other trustedzone on one of the two (`POLYGON AMOY_POX10 runs only its trustedzones (ecld-pynithy-amoy-pox10, ecld-nodenithy-amoy-pox10), and ecld-pynithy-amoy is not one of them`).

This rule and the `-unsafe` rule of "Choosing the trustedzone" are asked by `run()`, by `run_session()` and by `attach_session(order_id, securelock_enclave)`, which reads the trustedzone from the order's request. The steps of a run called directly (`check_allowance()`, `create_task()`, `create_do_request()`, `approve_order()`, `cancel_unclaimed_request()`) and `attach_session(order_id)` without a securelock ask neither rule: they act on the network the runner is on, whatever trustedzone a request names.

The trustedzones of both networks are signed for production and take their sessions from Scontain's CAS, as the mainnets' do; neither network has an `-unsafe` network. Neither is among `ipfs.INTAKE_NETWORKS`: while the storage is the bootnode's payload intake, which is the default, `run()`, `run_session()` and `attach_session(order_id, securelock_enclave)` refuse before any transaction, so call `set_storage_ipfs(url, token)` first (see "Storage and the result read").

### Changing the network

`runner.set_network(name, type)` moves a runner to another network of the table, before or after `connect()`. On a connected runner it builds the protocol and token contracts again for the network set, as `connect()` builds them, so every later read and transaction goes to that network's contracts at its RPC, signed for its chain; the image registry is read from the network set at the next run. The key, a storage set with `set_storage_ipfs`, the resources and the last run's result stay; the order with its request's challenge and block, the node and the enclave details of the network left are dropped, and an intake storage is rebuilt under the new network's key. The protocol contract of the network left sends nothing more: a transaction asked of it raises `errors.RunEndedError`.

- A ceiling set with `set_max_fee_per_gas` stays with the runner: it is the ceiling on the network set, ahead of that network's default.
- A call that names the network the runner is on does all of the above as well: on a connected runner the contracts are built again, and the order, the node and the enclave details are dropped.
- The ESR state cache keeps each network's states under that network: `esr_read` serves a state only on the network it was cached on. In a cache file (`enable_state_cache(file=...)`) the key of an entry is `<network>_<type>|<enclave wallet>|<state key>`, the network and the wallet in lower case (`polygon_amoy|0x5e...|counter`). An entry under `<enclave wallet>|<state key>` alone, the key `ethernity-cloud-runner-py` 0.5.38 wrote, is served when the network has no entry of its own for the wallet and the key, the entry's cid is not empty and the network's Enclave State Registry holds that cid; it is then written under the network's key as well, and stays under its own. Entries under any other key are not read.
- `esr_read` reads the network once, as it begins: its cache key, its free check and its state-fetch task are those of that network. When the runner was moved before the task would be run, `esr_read` raises `RuntimeError` and runs none.

A call that raises leaves the runner on its network, unchanged:

- `ValueError` for a name or a type the table does not hold;
- `RuntimeError` while something of the runner is in progress: a run whose thread is at work, after which the call is taken; a `connect()`, a `run_session()` or an `attach_session()` under way in another thread; or a session handle the runner returned, which keeps the runner in progress until its `session.close(wait=True)` has returned the session's summary or the runner is closed with `runner.close()`, whatever became of a later `run_session()` or `attach_session()` of the same runner. After `close()` the runner takes the key and `connect()` again. Another `EthernityCloudRunner` serves the other network meanwhile;
- `RuntimeError` after `close()` while the thread of the run it ended is still at work, and when `close()` was called while the call waited (see "Closing the runner");
- `ConnectionError` when the provider of the network set does not answer a connected runner.

### Changing the wallet

`runner.set_private_key(key)` gives a runner another wallet, before or after `connect()`; the key is 64 hex digits prefixed with `0x`. On a connected runner it builds the protocol contract again for the runner's network with the new signer, as `connect()` builds it, so every later transaction is signed by the new wallet and every read (its balance, its allowance, its orders) is made for it. The network, the storage, the ceiling set with `set_max_fee_per_gas`, the resources, the ESR state cache and the last run's result stay; the order the previous wallet had in hand, with its request's challenge and block and its node, is dropped. The protocol contract built with the previous signer sends nothing more: a transaction asked of it raises `errors.RunEndedError`.

A call that raises leaves the runner with its wallet, unchanged, and no message of the call holds the key:

- `ValueError` for a string of another form (`Invalid private key format. Must be 64 hex chars prefixed with 0x.`), for the key zero (`Invalid private key: it is zero, and a secp256k1 private key is from 1 to the order of the curve less 1.`), and the error `eth_account` raises for a key it does not take;
- `RuntimeError` while something of the runner is in progress, after `close()` while the thread of the run it ended is still at work, and when `close()` was called while the call waited, as `set_network` raises them: another `EthernityCloudRunner` serves the other wallet meanwhile.

### One runner, several threads

`connect()`, `run()`, `run_session()` and `attach_session()` work under one lock of the runner: `connect()` and `run()` hold it while they build the contract or start the run's thread, `run_session()` and `attach_session()` for the whole call. A call made while another holds the lock waits for it. `set_network()` and `set_private_key()` take the same lock without waiting, so a change of the network or the wallet made from another thread is done before such a call starts or is refused during it, and a submission is sent to one network with one wallet.

An order id names an order of one network and one wallet, those the runner has when `attach_session()` is called. An `attach_session()` that waited for a `set_network()` or a `set_private_key()` reads nothing and raises `RuntimeError`; one that waited while `close()` was called raises the error of a closed runner below; one that waited for anything else attaches once that is done:

```
attach_session() waited for a change of this runner, which is on POLYGON AMOY_POX10 with the wallet 0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A; order 7 was asked for on POLYGON AMOY with the wallet 0x19E7E376E7C213B7E7e7e46cc70A5dD086DAff2A, and an order id names an order of one network and one wallet. Call attach_session() again for the order meant.
```

`run()`, `run_session()` and `attach_session()` raise `RuntimeError("A task is already running.")` while a run of the runner is in progress, and a refused call changes nothing of that run; `run()` raises it while a session handle of the runner is open as well. One runner serves one run at a time: use one `EthernityCloudRunner` per task for tasks in parallel.

`close()` is serialised with `connect()`, `set_network()` and `set_private_key()`. One of them that is building and assigning the runner's contract, network or key when `close()` is called is waited for (one RPC request at most, see "RPC requests"), and `close()` then ends what it assigned. One that began before `close()` was done and waited for it does nothing and raises `RuntimeError`; so do `connect()`, `run()`, `run_session()` and `attach_session()` when they waited for the runner's lock while `close()` was called:

```
The runner was closed with close() while set_network() waited for it: set_network() did nothing. A closed runner takes a key with set_private_key() and connect() again; another EthernityCloudRunner serves meanwhile.
```

### Session handles

The handle `run_session()` or `attach_session()` returns works through what the runner held when the handle was made, whatever the runner holds later: its input rows and its close row go through that protocol contract (its network, its PoX and its signer), its reads are made on it, its inputs are sealed for the trustedzone certificate of that time, and its signatures and decryptions use the wallet key of that time. An input's bytes go through the storage the runner has when the input is sent, so `set_storage_ipfs` during a session serves the inputs after it.

A handle keeps its runner in progress until its `session.close(wait=True)` has returned the session's summary, or until `runner.close()`: `set_network()`, `set_private_key()` and `run()` are refused meanwhile, and a `run_session()` or an `attach_session()` of the same runner that fails does not end that. Once `session.close(wait=True)` has returned, the handle is out of the runner's handles and the runner takes those calls again while it holds no other handle; a later `close(wait=True)` of the handle returns the same summary and reads nothing. After `session.close(wait=False)` the runner keeps the handle, and `set_network()` and `set_private_key()` stay refused, since a `close(wait=True)` made later reads the summary through the runner. `runner.close()` detaches every handle the runner holds (see "Closing the runner").

`session.close(wait=True)` reads the summary of the handle's own order, within that order's duration, and checks the signer of its result transaction as well as its order, contract and chain. The handle of `run_session()` checks the signer against the challenge of its request. A process that attaches does not know the challenge: the handle of `attach_session()` checks the signer against the task wallet the trustedzone attested in the session's `etny-sw` row, verified against the trustedzone's certificate in the Image Registry, which is the wallet both trustedzones sign the result with. A result another wallet signed gives no summary (`None`), and so does an attached handle that has verified no attestation, as an attached handle's `close(wait=True)` did on 0.5.38: a result whose signer is not checked is never taken, and the ESR wallet and state its envelope names reach neither the wallet `esr_read()` and `esr_version()` use nor the state cache. The summary's `input_transaction_hash`, `image_hash`, `script_hash` and `file_set_hash` are those of the session's request for the handle of `run_session()`, whatever task the runner has sent since, and `None` for the handle of `attach_session()`. `runner.attach_task(order_id)` reads a result only on a runner that holds the challenge of the order's request, and returns `None` on any other. `poll_outputs()` reads the rows in one thread at a time, so `on_output()` and `wait_output()`, `wait_outputs()` or `close()` in another thread take each message once.

### Closing the runner

`runner.close()` stops the runner, drops its key, its contracts and its storage, and ends what is in progress:

- A run in progress ends. Its thread sends no transaction after `close()` returns: a transaction it is handing to the node when `close()` is called is handed over first, `close()` waiting for that one request, and a send it reaches later raises `errors.RunEndedError` inside the thread and is not made; nothing is tried again, and the runner's status and error stay as `close()` set them. `close()` waits two block times for the thread. A thread still at work after that (in a request to the RPC or the storage, or in a wait between two) is waited for again by the next `connect()`, `run()`, `run_session()`, `attach_session()`, `set_network()` or `set_private_key()`, for up to `RUN_END_WAIT_SECONDS` (30 s, a constant of `ethernity_cloud_runner_py.runner`); the call is taken once the thread has ended and raises `RuntimeError` otherwise:

```
The run this runner was closed during is still at work in its thread, which was waited for 30 s: connect() is refused until that thread has ended. The thread sends no transaction. Call again later, or use another EthernityCloudRunner.
```

  The thread can be in a wait longer than 30 s when the runner is closed, and the next call then raises this error after 30 s while the thread sends nothing: the wait for a node's order backs off up to 600 s after a read that failed, `retry_operation` up to 60 s between two tries, a resubmission after an operator fault waits `retry_delay` (30 s by default), a read of the storage takes up to 70 s per endpoint and a delivery to the payload intake up to 120 s.
- A `run_session()` or an `attach_session()` under way in another thread sends nothing more, returns no handle and raises `errors.RunEndedError`; where the call was in a read or a wait when the runner was closed, the error of that step is the cause of the `RunEndedError`. When a `run_session()` had sent its DO request, which holds the request's escrow once mined, the error names it (also a request a hand-over of which to the node went unanswered before `close()`, which the node may mine), its `request_id` (once read from the receipt) and `request_hash` attributes carry it, and its message says how the escrow comes back: on a connected runner of the same network and wallet, `runner.contract.cancel_do_request(request_id)` returns it while no node has taken the request; once a node has placed an order on it, `list_sessions()` names the order and `attach_session(order_id)` gives a handle that closes it.
- Every session handle the runner returned is detached. Its `send_input()`, `poll_outputs()`, `wait_output()`, `wait_outputs()` and `close()` raise `SessionError` and send nothing, its `is_running()` answers `False`, and it keeps no key:

```
The runner was closed with close(): this handle of a session on POLYGON AMOY sends and reads nothing more. The session's order stays as it is on chain; attach_session(order_id) on a connected runner of that network and wallet gives a new handle.
```

- No protocol contract the runner built sends anything more: a transaction asked of it raises `errors.RunEndedError`. That is the contract the runner held, the one a run began with and the one a handle was made with, which are other objects than the runner's when `connect()` was called again since, and any other the runner built that is still referenced.
- A `connect()`, `set_network()` or `set_private_key()` of another thread is waited for and its outcome ended, or it raises (see "One runner, several threads").
- A closed runner holds no protocol contract: `run()`, `run_session()` and `attach_session()` raise `RuntimeError` before they write or send anything, as they do on a runner never connected, until a key is set and `connect()` is called again:

```
run() needs a connected runner: this one holds no protocol contract (it was not connected, or it was closed with close()). Give it a key with set_private_key() and call connect() first.
```

### RPC requests

Each call to a network's RPC is one HTTP request, which web3 does not send again (`rpc.rpc_provider`): its timeout is 5 s for the connection, which a slow TLS handshake passes, and 10 s for the answer (`rpc.RPC_TIMEOUT`), and in the thread that built the contract a connection that cannot be made is tried once more, at once. One request takes 20 s at its longest (`rpc.RPC_REQUEST_MAX_SECONDS`: two connections that each take their 5 s and an answer that does not come in 10 s), 15 s in another thread; an RPC that accepts the connection and never answers takes 10 s. web3 asks the chain id (`eth_chainId`) before every call, gas estimate and transaction it validates; a provider asks it once in each thread and keeps the answer, since an RPC's chain does not change, and asks every other request each time.

What is asked again is asked by the runner, between two requests, and not again in the thread of a run `close()` ended:

- a send hands its signed transaction to the node again, the same bytes, while the hand-over is not answered (an HTTP 429, 503 or 504, a connection reset, an answer later than 10 s, a body that is no JSON-RPC answer), up to five times two seconds apart (`HANDOVER_ATTEMPTS`, `HANDOVER_RETRY_SECONDS` of `contract.operation.protocolContract`). The same bytes are the same transaction: a node that holds it answers so ("already known", bloxberg's "Transaction with the same hash was already imported.", matched as whole phrases), and the send takes its hash. A hand-over the RPC refuses without passing it on (an HTTP 429, a connection that was never made: refused, or not made within the connect timeout; `refused_untaken`) leaves the transaction the runner's: when all five are refused so, the send raises `Unable to send transaction: ...`, and the tries of the DO request and of the order's approval sign it again at the same nonce. Once a hand-over has gone unanswered in another way (an answer later than 10 s or a connection reset after the request was sent, an HTTP 503, which a gateway answers also for a request it passed on, an HTTP 504 or another error status, a body that is no JSON-RPC answer), the node, or another replica behind the RPC, may hold the transaction, so the send takes its hash whatever the node answers next, an answer that its nonce is used among them (geth's and bor's "nonce too low", Nethermind's "OldNonce", OpenEthereum's "Transaction nonce is too low"), and also when no later hand-over is answered; its receipt then decides. No other transaction is built for that intent while it may be mined, by the send or by the step that called it: the tries of the DO request and of the order's approval end with that send, and `approve_task` sends no second approval once one was handed over; a step whose receipt does not come sends nothing again. When another sender of the same wallet takes the nonce of such a transaction, the transaction can never be mined, and the step ends when its receipt wait does: after 100 blocks the token approval raises `ValueError("Allowance approval failed.")`, the DO request ends the run with "Unable to create a DO request", the order's approval ends it with "Task approval failed." while the order the node placed on the request stays unapproved with the request's escrow, and the cancel of a request reports the request as one no node took, its escrow left in it; after 60 blocks a session's `send_input()` raises `SessionError` ("input row transaction failed"), and `close()` goes on without its close row mined, so the session's order stays in progress until its duration ends. When every hand-over made before the node answers that the nonce is used was refused untaken, that answer refuses this transaction, which no node holds, and the send builds it again at the nonce read again. A node error answering a hand-over before any went unanswered says the node did not take the transaction: a nonce it refuses gives another attempt of the send at the nonce read again, and any other error is raised, which the tries of the DO request and of the approval take as a failed try. A nonce, fee or gas estimate read the RPC does not serve ends an attempt of the send, and the next attempt reads again a second later;
- the reads before a request, `attach_session()`'s reads of the order and of its request, the node check, `esr_version()` and `esr_nonce()` are asked up to three times, two seconds apart, while the RPC does not serve them (`rpc.read_again`); a read the contract refuses (a revert) is raised at once;
- the question whether the RPC answers (`connect()`, `set_network()`, the check at the start of a run or a session) is asked up to three times, two seconds apart, while the RPC refuses it (an HTTP error status, a connection refused or reset) and not again after a question that timed out (`rpc.rpc_answers`): `connect()` or `set_network()` on an RPC that does not answer takes one request, 20 s at its longest;
- the receipt, order and result polls read again at their next poll, a session handle's reads of its order, its request and its input rows are asked up to three times, and the ESR version wait reads again at its next interval.

### Closing a session

`session.close(wait=True, timeout=900)` writes the session's close row. With `wait` true it then waits until the order has closed and returns the order's result, the session summary. The answers to the session's inputs are output rows and arrive before the close; the order closes after the trustedzone has found those rows on chain and the node has sent the result, which takes at least one more block. An application that does not read the summary calls `session.close(wait=False)`, which returns once the close row is mined.

The runner accepts a result only when the transaction the enclave signed is `_addResultToOrder` for this order, addressed to this network's protocol contract and signed for this chain, and its signer is the wallet derived from the task's challenge.

### `___etny_result___` function

The `___etny_result___` function is a special function used in Ethernity Cloud Runner tasks. When executing a task, this function allows the task code to send the result back from the Ethernity Cloud platform.

In the context of the Ethernity Cloud Runner, tasks are executed in a decentralized and distributed manner. The `___etny_result___` function acts as a communication channel between the task code and the Ethernity Cloud platform. When the function is called with the result data as its argument, it sends the result back to the platform, where it can be processed and stored.

This special function plays a crucial role in ensuring that the results of executed tasks are properly recorded and accessible. It enables seamless interaction with the Ethernity Cloud platform, making it a key component of the Ethernity Cloud Runner's functionality.


### Following progress

`run()` returns as soon as the task is handed to a thread of its own; the runner is polled for its state:

- `is_running()` is `True` while that thread works and `False` once the task has finished or failed.
- `get_state()` returns a dict: `status` is the `ECStatus` name, `RUNNING` until the task ends in `SUCCESS` or `ERROR`; `progress` is the `ECEvent` name of the step the task is at; `last_error` is the message of the failure that set `ERROR`, `None` otherwise; `result` is what `get_result()` returns; `processed_events` lists the `ECEvent` names already completed and `remaining_events` those still queued.
- `get_result()` returns `None` until the task has finished, then a dict whose `value` is what the task passed to `___etny_result___`, `result_task_code` the name of the enclave's task code (`SUCCESS`, `PAYLOAD_CHECKSUM_ERROR`, ...), `result_task_code_int` its number, `success` whether that code is `0`, and `order_id` the order the result was read from.

A task the enclave reports with a non-zero task code, such as `BASE_EXCEPTION` for an exception raised in the dApp, ends in `ERROR`: `last_error` names the code, and `get_result()` still returns the result, whose `value` is the enclave's error report (for an exception, its traceback).

### Input dataset

`run(..., input_data="...")` sends a string to the task as its input dataset, read in the payload as `___etny_data_set___` (`ecld.input`). It is encrypted for the trustedzone and stored like the payload, and the request carries its sha256, which the trustedzone verifies before the securelock receives it. An interactive session takes its inputs through `send_input` instead.

Every artefact (challenge, payload, input) is stored as an IPFS node with its default settings stores a file added with `--cid-version=1 --raw-leaves`: in blocks of 256 KiB, a single block as it is, several under a UnixFS tree. The runner computes that CID itself, so an artefact of any size is named in the request before it is uploaded, and the bootnode's payload intake takes it up to its 100 MiB body cap.

The `ECEvent` steps, in order: `INIT` (the wallet balance, the protocol contract, the node address and the enclave's registry entry are checked, the DO request is placed and the artefacts delivered), `CREATED` (waits for a node to place an order), `ORDER_PLACED` (the order is approved), `IN_PROGRESS` (the result is awaited and verified) and `FINISHED`. A protocol contract its storage does not list as an allowed caller, the state of a contract another one has replaced, fails the task at `INIT`, before any allowance is approved for it: `last_error` names the contract and its storage and advises upgrading `ethernity-cloud-runner-py`. A failure on the operator's side (an order that times out, a result that does not verify, an operator-fault task code) resubmits the task as a new DO request up to `max_retries` times (an argument of `run()`, 2 by default) before `ERROR` is set.

### Task resources

```python
resources = {
    'taskPrice': 10,
    'cpu': 1,
    'memory': 1,
    'storage': 40,
    'bandwidth': 1,
    'duration': 1,
    'validators': 1
}
```

The `resources` parameter, the first argument of the `run` method, is a dict that defines the resource requirements for executing a new task using the Python/Node.js template. It specifies the amount of various resources needed for the task to be processed on the EthernityCloud network. The `resources` object contains the following properties:

1. `taskPrice`: the most the user pays per hour of the task, in whole tokens (tETNY on bloxberg). A node takes the order when this covers its own price plus the fees the network adds to it: 5% for Ethernity, 2% for the validator, and the publishers' fees of the two images the task runs with (the trustedzone template's, 10% unless its publisher set another, and the securelock's, 0 unless its publisher set one), so a node asking 1 token is taken from a price of 2 with the default fees.

2. `cpu`: This specifies the amount of CPU (Central Processing Unit) resources required for the task. It indicates the computational power needed to execute the task's code.

3. `memory`: This indicates the amount of RAM memory required for the task's execution. It represents the storage space in RAM memory needed to run the task.

4. `storage`: This property represents the storage space needed for the task's execution. It indicates the amount of disk space required for the task.

5. `bandwidth`: This defines the amount of network bandwidth required for the task's execution. It represents the data transfer capacity needed to perform the task.

6. `duration`: This specifies the time duration or the maximum time allowed for the task's execution. It sets a time limit for how long the task can run.

7. `validators`: This property determines the number of validators required for the task. Validators are nodes on the network responsible for processing and validating tasks.

By providing these resource requirements in the `resources` object, the task execution engine (EthernityCloudRunner) can use this information to allocate the necessary resources and process the task accordingly on the specified TESTNET network.

When no node places an order on the request within the order wait (`runner.set_order_wait(seconds)`, default 1800), the runner cancels the request, which returns its escrow, and the task fails. If a node booked the request just before the cancel, the cancel is refused by the contract and the task goes on with that node's order.

### Requests served by claims (PoX 2.0 matching)

Before each request the runner reads the network's PoX: its `VERSION()`, and its pricing's `matching()` (`pricingAddress()`, then the pricing's `matching()`), on every network whose PoX is apart from its token; on the bloxberg mainnet PoX and its `TESTNET_POX10` copy, which are their own tokens, it reads nothing of them. A network whose pricing names a PoxMatching serves its requests by claims while PoxMatching's `claimsOn()` answers true, and the runner reads the PoxMatchReader's address from PoxMatching's `reader()`; no network entry names a PoxMatching. On every other network, the PoX 1.0 networks among them, and while claims are off, a request is added and approved as described above: with V2 terms when `resources` gives `max_price_per_cu_hour_wei` with an `escrow_wei` (`addDORequestV2` in the form `VERSION()` names: "2.0" with the minimum EPC, "1.2" without; refused on a PoX that answers neither), without terms when it gives no `escrow_wei` (which is told) or no V2 key at all. On a network with PoxMatching a request pinned to a node (`node_address`) that is banned is refused before it is sent, with the end of the ban, and the stored result of an order is read by the grammar of `spec/matching.md` section 17: one outside it carries no enclave transaction and is the operator's fault.

A request with V2 terms takes these keys of `resources` besides the ones above: one instance (`validators` 1, more refused under claims), each of `cpu`, `memory`, `storage` and `bandwidth` 1 to 255 when given (left out, it takes its default) and a `duration` of 1 hour or more; on a PoX answering "2.0" the duration is at most the pricing's `maxOrderHours` and the GFLOPS ceiling at most its `gflopsMax`, both read before the request. Every term the PoX would refuse is refused before anything is sent, naming the PoX's revert string (`spec/matching.md` section 4); a metadata string of more than 2,048 bytes is refused after the approval and before the add.

| Key | Meaning | Default |
|---|---|---|
| `max_price_per_cu_hour_wei` | the bid per CU-hour, wei, 1 to 2^128 - 1 | required |
| `escrow_wei` | the escrow `addDORequestV2` pulls, wei; on the claims path the most it may pull, the escrow itself being the reader's `escrowFor` at the request's terms (the work at the bid with its fees, plus the chain fee) | none |
| `max_gflops` | the GFLOPS ceiling of the node paid for (one CU is 100 GFLOPS) | 0, none |
| `required_gflops` | the GFLOPS the request requires, at most a stated ceiling | 0, one CU |
| `relays_per_hour`, `gas_level` | the chain fee's relays per hour and gas level (1e18 the average gas price; 1e18 to 2^128 - 1) | 0, 1e18 |
| `epc_mib` | the client's EPC figure in MiB, rounded up to units of 64 MiB; the request states the largest of one unit, the image's recorded need (`imageEpcUnits`) and this | 0 |
| `max_bid_per_cu_hour_wei` | the bid ceiling a raise of the bid stays within, 1 to 2^128 - 1 | none: a raise is reported, not sent |
| `min_node_score` | the minimum node score, in points (0.50); 0 switches the test off | see below |
| `recent_failure_slots` | a claimer whose last failed order is fewer slots ago is approved only when no other claim stands | 14 |
| `allow_marked_image` | send a request for an image marked likely broken | False |
| `expire_unstarted`, `note_refund`, `note_ambiguous` | end an order not started 900 s after its approval; record an expired order against its node; send `noteAmbiguous` an hour after a result the validators have not noted | True |

Before the add the runner reads the trustedzone template's record, the image's health (a marked image is refused unless `allow_marked_image` is set), the image's records in the image registry (`ECImageRegistryV4.imageRecords`: its kind, a default release and which, native Python or a custom securelock, whether its network is on, its enclave memory and its minimum operator score, all told to the client; an image its session name's newest version is not bound to is refused, naming the dApp's current image), the request's memory need (the larger of `memory` and the image's enclave memory) and minimum EPC, both told to the client, the quote at the request's terms (`bidQuoteFor`) and the escrow the add pulls (`escrowFor`), against which it checks the balance and sets the allowance; an escrow above `escrow_wei` is refused, as is an image registry that does not answer the EPC need's read and a metadata string of more than 2,048 bytes. After the add it reads the request at every block on the parameter set `requestInfo` names while the request takes claims (its set has claims on, the storage holds it AVAILABLE and it is at most `maxRequestAgeSeconds` old: a request past its age is cancelled, and one whose set has claims off is waited for and approved as described above), approves a claim by the design's rule (3.10), the node mandated for the step first, an in-time claim before a late one, a mandated node that can no longer claim (`canClaimOf`) passed over at once, and raises the bid to the quote's lowest matching bid within `max_bid_per_cu_hour_wei` when no claim it would approve can come. The minimum score is `min_node_score` when set; else the dApp's minimum operator score its records hold, 0 switching the test off; else, for a dApp of the default class, 0.50 once the network's first node reached 1.00 (`minimumOn()`); else the top tier of the request's round (`tierScore`). The runner passes over the nodes of its local list (two of its orders of the dApp on the node ended in 20, 62, a 33 before its time, 59 or 63 within 7 days; PoxMatching's `early33` judges a 33) and, for a paid class, those the image's counted failures of the last 7 days name. What it tells the client is logged and kept in `runner.matching_notices`; a code 20, 62, 44, 47, 59 or 63, or a 33 before its time (settled as a 62), is reported by the class the result states in `last_error` and the result's `end_report`. An expiry the PoX does not admit yet and a `noteAmbiguous` due later are kept in `runner.matching_pending` and sent by `runner.settle_matching()`, which a later request served by claims calls before its add.

### The fee ceiling

On a network with EIP-1559 fees (Polygon mainnet and Polygon Amoy, the IoTeX Testnet, Ethereum Sepolia, LitVM LiteForge) every transaction the runner sends (the token approval, the DO request, the approval of an order, the cancel of a request, a session's input and close rows, a testnet faucet draw) offers a `maxFeePerGas` of the latest block's base fee plus 10 %, plus the network's priority fee, and is sent only when that fee is within a ceiling. The ceiling is, in this order:

- the value given to `runner.set_max_fee_per_gas(gwei)`, which is called before or after `connect()`;
- the environment variable `ECLD_MAX_FEE_PER_GAS`, when it is set and not empty; it is read at each send;
- the network's default, the `MAX_FEE_PER_GAS` of its `ECNetwork` entry: 500 gwei on Polygon mainnet and on Polygon Amoy (its `-unsafe` and its PoX 1.0 network included), 1500 on the IoTeX Testnet, 15 on Ethereum Sepolia and 2 on LitVM LiteForge.

The setter takes a positive whole number of gwei as an `int` and raises `ValueError` for anything else; the variable holds one in decimal digits alone, at most 30 of them. Either is the ceiling on whichever of these networks the runner is on. The bloxberg networks send at a fixed gas price and read none of the three.

A transaction whose fee is above the ceiling is not sent: the send raises `FeeCeilingError` (`ethernity_cloud_runner_py.errors`), whose message states the base fee, the fee computed, the ceiling and what set it. So does every send while the variable is the ceiling in force and holds anything but a positive whole number of gwei, or one of more digits than Python's `int()` converts; that message names the variable and its value. A token approval, a faucet draw or a DO request that is refused is not tried again: the run ends at once in `ERROR` with the message as `last_error`, and `run_session()` raises the error, as a session's `send_input()` and `close()` do for their rows. The approval of an order, which the placed order waits for, is tried again after a refusal as after any other failed send: up to 50 tries, the waits between them doubling from the network's block time to a minute, each refusal printed. A ceiling raised with `set_max_fee_per_gas` meanwhile holds from the next try, and a submission whose every try is refused ends with the message. The ceiling set is that of every protocol contract of the runner from its next send on: the one the runner holds, the one a run in progress began with and the one each session handle was made with, when `connect()` was called since. The refused cancel of a request no node took is logged as an error; the request stays open with its escrow, and the run ends as one no node took. With the default on Polygon mainnet and on Polygon Amoy, whose priority fee is 32 gwei, a base fee up to 425.45 gwei is sent, and one of 426 gwei is refused with:

```
The network's base fee is 426 gwei; the maxFeePerGas computed for the transaction, 500.6 gwei (the base fee plus 10 %, plus the priority fee of 32 gwei), is above the fee ceiling of 500 gwei (the network's default), so the transaction was not sent. To send at this fee, raise the ceiling with EthernityCloudRunner.set_max_fee_per_gas(gwei) or, where that was not called, with the environment variable ECLD_MAX_FEE_PER_GAS (a whole number of gwei).
```

### Storage and the result read

A runner that configures no storage delivers the task's artefacts (the encrypted challenge, code and session inputs) through the bootnode's payload intake: each CID is computed locally and the bytes are posted to `https://ipfs.ethernity.cloud/payload/<network>/<doRequestId>/<cid>` once the DO request is on chain, with no token. The intake serves the networks the bootnode's agent runs, today the bloxberg testnet, Polygon Amoy, LitVM LiteForge and Ethereum Sepolia, each with its `-unsafe` twin (`ipfs.INTAKE_NETWORKS`). `set_public_intake()` configures the same storage explicitly, and takes the base URL of another intake.

Each blob queued for the intake belongs to the operation that queued it: a task (its challenge, code and input, delivered under its DO request) or a session handle (its inputs, delivered under the session's request). A delivery posts the blobs of its own operation alone, so a task and a session of one runner, or two sessions, never post or drop each other's blobs. A task's blobs are out of the queue once its request has been attempted: delivered when the request is on chain, dropped when the request was not sent or the delivery failed. A session input's blob is dropped when its row was not sent or was mined as reverted; one whose row has no receipt yet stays queued under its handle and goes out with the delivery after the handle's next input row.

On a network the intake does not serve, a run with the default storage fails at delivery, after the DO request is on chain: the intake answers 404 for the network and the runner stops with a message that names `set_storage_ipfs`. Such a runner must call `set_storage_ipfs(url, token)` before `run()`. On a `MAINNET` network type the runner builds no default at all: `run()`, `run_session()` and `attach_session(order_id, securelock_enclave)` refuse before any transaction unless `set_storage_ipfs` or `set_public_intake` was called.

`set_storage_ipfs(url, token)` uploads and reads through a Kubo RPC API instead: one of your own, or the public API `https://ipfs.ethernity.cloud/api/v0` with a writer token as `token`, which the runner sends verbatim as the `Authorization` header of every request. Without a token the public API answers `add` with 403, and the run stops at once with a message that says so.

Reads stay open on the public API: a result is read from the configured API's `cat` first and from the public gateway `https://ipfs.io` second, without credentials; each request is abandoned after 60 seconds, and the read is repeated until the order's deadline (its duration plus 15 minutes, and at least two minutes after it closed) before the task is reported as not downloadable.
