"""tests/spec/ holds byte-identical copies of pox-smart-contract-litvm's
spec/result-v5.json and spec/MANIFEST.sha256 (the sha256sum text format, LF
lines). The copy must hash to its manifest line and, where a
pox-smart-contract-litvm checkout sits above this repository, both copies
must equal the source bytes."""
import hashlib
import re
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parent / "spec"
REPO = Path(__file__).resolve().parents[1]
MANIFEST = "MANIFEST.sha256"
COPIES = ["result-v5.json"]
LINE = re.compile(r"^([0-9a-f]{64})  ([^\s/]+)$")


def manifest():
    text = (SPEC / MANIFEST).read_bytes()
    assert text.endswith(b"\n") and b"\r" not in text
    entries = {}
    for line in text.decode("ascii").rstrip("\n").split("\n"):
        m = LINE.match(line)
        assert m, "manifest line is not '<sha256>  <name>': %r" % line
        entries[m.group(2)] = m.group(1)
    return entries


def source_dir():
    for base in REPO.parents:
        candidate = base / "pox-smart-contract-litvm" / "spec"
        if (candidate / MANIFEST).is_file():
            return candidate
    return None


@pytest.mark.parametrize("name", COPIES)
def test_each_copy_hashes_to_its_manifest_line(name):
    assert hashlib.sha256((SPEC / name).read_bytes()).hexdigest() == manifest()[name]


def test_the_copies_equal_the_litvm_checkout_when_present():
    source = source_dir()
    if source is None:
        pytest.skip("no pox-smart-contract-litvm checkout above this repository")
    for name in [MANIFEST] + COPIES:
        assert (SPEC / name).read_bytes() == (source / name).read_bytes(), name
