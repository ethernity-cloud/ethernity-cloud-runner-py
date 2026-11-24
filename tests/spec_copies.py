"""The copies of pox-smart-contract-litvm's spec/ the suite holds in
tests/spec/, taken at SOURCE_COMMIT (spec/README.md "Pinning a copy"), and
the checkout their source-commit tests read that commit from with `git
show`: the directory POX_SMART_CONTRACT_LITVM names, else the first
pox-smart-contract-litvm beside this repository or beside any directory
above it. A checkout's working tree is never read."""
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

SPEC = Path(__file__).resolve().parent / "spec"
REPO = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "2f600f6"
SOURCE_ENV = "POX_SMART_CONTRACT_LITVM"
MANIFEST = "MANIFEST.sha256"
COPIES = ["abi-selectors.json", "capability-record.json", "matching-rank.json", "matching.md", "ranking.json",
          "reserved-prefixes.json", "result-fields.json", "result-v5.json", "runner-terms.json", "session-rows.json"]


def load(name: str):
    """The parsed JSON copy `name`."""
    return json.loads((SPEC / name).read_text(encoding="utf-8"))


def checkout() -> Optional[Path]:
    """The pox-smart-contract-litvm checkout the source-commit tests read,
    None when there is none."""
    named = os.environ.get(SOURCE_ENV)
    if named:
        return Path(named) if (Path(named) / ".git").exists() else None
    for base in REPO.parents:
        candidate = base / "pox-smart-contract-litvm"
        if (candidate / ".git").exists():
            return candidate
    return None


def shown(path: str, commit: str = SOURCE_COMMIT) -> Optional[bytes]:
    """The bytes of `path` at `commit` in the checkout (`git show`), None
    when there is no checkout or it holds no such commit or path."""
    source = checkout()
    if source is None:
        return None
    result = subprocess.run(["git", "-C", str(source), "show", f"{commit}:{path}"], capture_output=True)
    return result.stdout if result.returncode == 0 else None
