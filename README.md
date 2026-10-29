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

The `ECEvent` steps, in order: `INIT` (the wallet balance, the node address and the enclave's registry entry are checked, the DO request is placed and the artefacts delivered), `CREATED` (waits for a node to place an order), `ORDER_PLACED` (the order is approved), `IN_PROGRESS` (the result is awaited and verified) and `FINISHED`. A failure on the operator's side (an order that times out, a result that does not verify, an operator-fault task code) resubmits the task as a new DO request up to `max_retries` times (an argument of `run()`, 2 by default) before `ERROR` is set.

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

### Storage and the result read

A runner that configures no storage delivers the task's artefacts (the encrypted challenge, code and session inputs) through the bootnode's payload intake: each CID is computed locally and the bytes are posted to `https://ipfs.ethernity.cloud/payload/<network>/<doRequestId>/<cid>` once the DO request is on chain, with no token. The intake serves the networks the bootnode's agent runs, today the bloxberg testnet, Polygon Amoy, LitVM LiteForge and Ethereum Sepolia, each with its `-unsafe` twin (`ipfs.INTAKE_NETWORKS`). `set_public_intake()` configures the same storage explicitly, and takes the base URL of another intake.

On a network the intake does not serve, a run with the default storage fails at delivery, after the DO request is on chain: the intake answers 404 for the network and the runner stops with a message that names `set_storage_ipfs`. Such a runner must call `set_storage_ipfs(url, token)` before `run()`. On a `MAINNET` network type the runner builds no default at all: `run()`, `run_session()` and `attach_session(order_id, securelock_enclave)` refuse before any transaction unless `set_storage_ipfs` or `set_public_intake` was called.

`set_storage_ipfs(url, token)` uploads and reads through a Kubo RPC API instead: one of your own, or the public API `https://ipfs.ethernity.cloud/api/v0` with a writer token as `token`, which the runner sends verbatim as the `Authorization` header of every request. Without a token the public API answers `add` with 403, and the run stops at once with a message that says so.

Reads stay open on the public API: a result is read from the configured API's `cat` first and from the public gateway `https://ipfs.io` second, without credentials; each request is abandoned after 60 seconds, and the read is repeated until the order's deadline (its duration plus 15 minutes, and at least two minutes after it closed) before the task is reported as not downloadable.
