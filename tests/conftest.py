"""The PoX generation a runner reads before a request and before it reads a
result (matchingContract.read_generation) answers, in every test that sets
none of its own, a PoX with no VERSION() and a pricing that names no
PoxMatching: the request and result paths of the PoX 1.x networks. A test
of the claims path or of V2 terms sets its own with monkeypatch."""
import pytest

from ethernity_cloud_runner_py import runner as runner_module
from ethernity_cloud_runner_py.contract.operation.matchingContract import NO_GENERATION


@pytest.fixture(autouse=True)
def generation_without_pox_matching(monkeypatch):
    monkeypatch.setattr(runner_module, "read_generation", lambda contract: NO_GENERATION)
