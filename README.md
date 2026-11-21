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

A handle keeps its runner in progress until its `session.close(wait=True)` has returned the session's summary, or until `runner.close()`: `set_network()`, `set_private_key()` and `run()` are refused meanwhile, and a `run_session()` or an `attach_session()` of the same runner that fails does not end that. Once `session.close(wait=True)` has returned, the handle is out of the runner's handles and the runner takes those calls again while it holds no other handle; a later `close(wait=True)` of the handle returns the same summary and reads nothing. After `session.close(wait=False)` the runner keeps the handle, since a `close(wait=True)` made later reads the summary through the runner. `runner.close()` detaches every handle the runner holds (see "Closing the runner").

### Closing the runner

`runner.close()` stops the runner, drops its key, its contracts and its storage, and ends what is in progress:

- A run in progress ends. Its thread sends no transaction after `close()` returns: a transaction it is handing to the node when `close()` is called is handed over first, `close()` waiting for that one request, and a send it reaches later raises `errors.RunEndedError` inside the thread and is not made; nothing is tried again, and the runner's status and error stay as `close()` set them. `close()` waits two block times for the thread. A thread still at work after that (in a request to the RPC or the storage, or in a wait between two) is waited for again by the next `connect()`, `run()`, `run_session()`, `attach_session()`, `set_network()` or `set_private_key()`, for up to `RUN_END_WAIT_SECONDS` (30 s, a constant of `ethernity_cloud_runner_py.runner`); the call is taken once the thread has ended and raises `RuntimeError` otherwise:

```
The run this runner was closed during is still at work in its thread, which was waited for 30 s: connect() is refused until that thread has ended. The thread sends no transaction. Call again later, or use another EthernityCloudRunner.
```

- A `run_session()` or an `attach_session()` under way in another thread sends nothing more, returns no handle and raises `errors.RunEndedError`; where the call was in a read or a wait when the runner was closed, the error of that step is the cause of the `RunEndedError`.
- Every session handle the runner returned is detached. Its `send_input()`, `poll_outputs()`, `wait_output()`, `wait_outputs()` and `close()` raise `SessionError` and send nothing, its `is_running()` answers `False`, and it keeps no key:

```
The runner was closed with close(): this handle of a session on POLYGON AMOY sends and reads nothing more. The session's order stays as it is on chain; attach_session(order_id) on a connected runner of that network and wallet gives a new handle.
```

- No protocol contract the runner built sends anything more: a transaction asked of it raises `errors.RunEndedError`. That is the contract the runner held, the one a run began with and the one a handle was made with, which are other objects than the runner's when `connect()` was called again since, and any other the runner built that is still referenced.
- A `connect()`, `set_network()` or `set_private_key()` of another thread is waited for and its outcome ended, or it raises (see "One runner, several threads").

### RPC requests

Each call to a network's RPC is one HTTP request, which web3 does not send again (`rpc.rpc_provider`): its timeout is 3 s for the connection and 10 s for the answer (`rpc.RPC_TIMEOUT`), and in the thread that built the contract a connection that cannot be made is tried twice more, 0 s and 1 s apart; a request the RPC may have received is never sent again. One request takes 20 s at its longest (`rpc.RPC_REQUEST_MAX_SECONDS`: three connections that each take their 3 s, the waits and an answer that does not come in 10 s), 13 s in another thread; an RPC that accepts the connection and never answers takes 10 s. What is asked again is asked by the runner, which stops for a run `close()` ended: the reads before a request, the receipt, order and result polls, the attempts of a send (a nonce, fee or gas estimate read the RPC does not serve ends the attempt, and the next one reads again a second later), a session handle's reads of its order, its request and its input rows (three tries, two seconds apart) and the ESR version wait.

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
