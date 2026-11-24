"""tests/spec/ holds byte-identical copies of pox-smart-contract-litvm's
spec/ files at spec_copies.SOURCE_COMMIT and one MANIFEST.sha256 holding
that commit's line of each copy, in name order (the sha256sum text format,
LF lines), so that `sha256sum -c MANIFEST.sha256` there checks every copy.
Each copy must hash to its line, and, where a checkout is found
(spec_copies.checkout), each copy and each line must equal the source
commit's, read with `git show`."""
import hashlib
import re

import pytest

import spec_copies
from spec_copies import COPIES, MANIFEST, SOURCE_COMMIT, SPEC, checkout, shown

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


def test_the_manifest_names_every_copy_the_directory_holds_in_name_order():
    names = list(manifest())
    assert names == sorted(names, key=lambda n: n.encode("utf-8"))
    assert names == COPIES
    assert sorted(p.name for p in SPEC.iterdir() if p.name != MANIFEST) == COPIES


@pytest.mark.parametrize("name", COPIES)
def test_each_copy_hashes_to_its_manifest_line(name):
    assert hashlib.sha256((SPEC / name).read_bytes()).hexdigest() == manifest()[name]


def _source_or_skip(path):
    found = shown(path)
    if found is None:
        pytest.skip(f"no pox-smart-contract-litvm checkout holding {SOURCE_COMMIT} (found: {checkout()})")
    return found


@pytest.mark.parametrize("name", COPIES)
def test_each_copy_is_the_source_commit_s(name):
    assert (SPEC / name).read_bytes() == _source_or_skip(f"spec/{name}")


def test_the_manifest_lines_are_the_source_commit_s():
    source = _source_or_skip(f"spec/{MANIFEST}").decode("ascii")
    lines = dict(reversed(line.split("  ")) for line in source.splitlines())
    assert {name: lines[name] for name in COPIES} == manifest()


def test_the_checkout_is_found_by_its_variable_before_any_parent(monkeypatch, tmp_path):
    monkeypatch.setenv("POX_SMART_CONTRACT_LITVM", str(tmp_path))
    assert checkout() is None
    (tmp_path / ".git").mkdir()
    assert checkout() == tmp_path


def test_without_the_variable_the_checkout_beside_a_directory_above_the_repository_is_found(monkeypatch, tmp_path):
    """A repository at ec-runner-py/pypi/ethernity-cloud-runner-py finds the
    checkout two directories above its own."""
    monkeypatch.delenv("POX_SMART_CONTRACT_LITVM", raising=False)
    repo = tmp_path / "ec-runner-py" / "pypi" / "ethernity-cloud-runner-py"
    repo.mkdir(parents=True)
    monkeypatch.setattr(spec_copies, "REPO", repo)
    (tmp_path / "pox-smart-contract-litvm" / ".git").mkdir(parents=True)
    assert checkout() == tmp_path / "pox-smart-contract-litvm"
