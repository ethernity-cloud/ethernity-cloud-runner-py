"""matching (MATCHING-DESIGN.md 3.10, 3.15, 4.4 to 4.6; spec/matching.md
sections 3 to 9, 13 and 17) on the shared fixtures of
pox-smart-contract-litvm spec/ at spec_copies.SOURCE_COMMIT, held byte for
byte in tests/spec/ (test_spec_fixture.py checks the copies), and the
runner's ABI entries (contract/abi/matchingAbi.py) against that commit's.

ranking.json holds, per ranking case, the reader's `candidates` answers;
the runner's merge of those pages, its list hash, its matching count, the
band each entry's place names and its mandated sequence equal the reader's
answers and each roll node's turn. matching-rank.json holds the reference
rule's results: the seed, the keys, the need, the template and image keys,
the list's order, the mandated sequence, the stop band, the steps, the
pages of a paged read, the approval rule's decisions and the bid a raise
sends. result-fields.json holds the results whose fields 15 to 17 are read
and those whose fields are not."""
import json

import pytest
from eth_utils import keccak

from ethernity_cloud_runner_py import matching
from ethernity_cloud_runner_py.contract.abi import matchingAbi
from ethernity_cloud_runner_py.contract.abi.polygonProtocolAbi import contract as polygon_abi
from ethernity_cloud_runner_py.contract.operation import matchingContract
from ethernity_cloud_runner_py.runner import EthernityCloudRunner
from spec_copies import SOURCE_COMMIT, checkout, load, shown

RANKING = load("ranking.json")
RANK = load("matching-rank.json")
FIELDS = load("result-fields.json")
RANK_CASES = {case["name"]: case for case in RANK["ranking"]}


# Where each group of the runner's ABI entries comes from, in the source
# commit unless another is named; an artifact holds its ABI under "abi".
# pox_1_2 is the V2 add of a PoX that answers VERSION() "1.2", the entry of
# 7611a81, before the minimum EPC took bits 32 to 47 of maxGflops.
ABI_SOURCES = {
    "pox": "abi/EthernityImplementationV2_2_0.json",
    "pox_1_2": ("7611a81", "abi/EthernityImplementationV2_2_0.json"),
    "pricing": "abi/IPoxPricing.json",
    "matching": "abi/IPoxMatching.json",
    "reader": "abi/IPoxMatchReader.json",
    "image_registry": "abi/IECImageRegistryV4.json",
    "session_registry": "artifacts/PoxMatchingState.sol/IMatchingSessionRegistry.json",
}
# The file of abi-selectors.json's `entries` each group's rows are in. The
# session registry (ethernity-cas's SessionRegistry, read through
# IMatchingSessionRegistry) is not among the ABIs abi-selectors.json lists;
# pox_1_2 is the `before` form of its `changed` addDORequestV2.
SELECTOR_FILES = {
    "pox": "EthernityImplementationV2_2_0.json",
    "pricing": "IPoxPricing.json",
    "matching": "IPoxMatching.json",
    "reader": "IPoxMatchReader.json",
    "image_registry": "ECImageRegistryV4.json",
}
SELECTORS = load("abi-selectors.json")
CHANGED = {c["name"]: c for c in SELECTORS["changed"]}


def bare(entry):
    """An ABI entry without the fields that do not change its encoding or
    names (internalType, and the legacy constant and payable)."""
    if isinstance(entry, dict):
        return {k: bare(v) for k, v in entry.items() if k not in ("internalType", "constant", "payable")}
    if isinstance(entry, list):
        return [bare(v) for v in entry]
    return entry


def input_types(entry):
    return [i["type"] for i in entry.get("inputs", [])]


@pytest.mark.parametrize("group", list(ABI_SOURCES))
def test_each_abi_entry_is_the_source_commit_s(group):
    commit, path = ABI_SOURCES[group] if isinstance(ABI_SOURCES[group], tuple) else (SOURCE_COMMIT, ABI_SOURCES[group])
    found = shown(path, commit)
    if found is None:
        pytest.skip(f"no pox-smart-contract-litvm checkout holding {commit} (found: {checkout()})")
    source = json.loads(found)
    source = source["abi"] if isinstance(source, dict) else source
    for entry in getattr(matchingAbi, group):
        found = [e for e in source if e.get("type") == entry["type"] and e.get("name") == entry["name"]
                 and input_types(e) == input_types(entry)]
        assert len(found) == 1, entry["name"]
        assert bare(found[0]) == bare(entry), entry["name"]


def canonical(param):
    """A parameter's type in a canonical signature: a tuple as its
    components' types in parentheses, with the tuple's array suffix."""
    kind = param["type"]
    if kind.startswith("tuple"):
        return "(" + ",".join(canonical(c) for c in param["components"]) + ")" + kind[len("tuple"):]
    return kind


def signature_of(entry):
    return f"{entry['name']}({','.join(canonical(i) for i in entry.get('inputs', []))})"


def selector_of(entry):
    """An event's topic0, a function's or an error's selector (abi-selectors.json
    `rule`)."""
    digest = keccak(text=signature_of(entry))
    return "0x" + (digest if entry["type"] == "event" else digest[:4]).hex()


@pytest.mark.parametrize("group", list(SELECTOR_FILES))
def test_each_abi_entry_is_its_row_of_abi_selectors(group):
    rows = {(r["abi"], r["kind"], r["signature"]): r.get("selector", r.get("topic0")) for r in SELECTORS["entries"]}
    for entry in getattr(matchingAbi, group):
        key = (SELECTOR_FILES[group], entry["type"], signature_of(entry))
        assert key in rows, key
        assert selector_of(entry) == rows[key], key


def test_the_1_2_add_is_the_before_form_of_the_changed_add():
    entry = next(e for e in matchingAbi.pox_1_2 if e.get("name") == "addDORequestV2")
    changed = CHANGED["addDORequestV2"]
    assert (signature_of(entry), selector_of(entry)) == (changed["before"], changed["beforeValue"])
    entry = next(e for e in matchingAbi.pox if e.get("name") == "addDORequestV2")
    assert (signature_of(entry), selector_of(entry)) == (changed["signature"], changed["now"])


@pytest.mark.parametrize("group,name", [("reader", "bidQuoteFor"), ("reader", "escrowFor")])
def test_each_changed_entry_the_runner_calls_is_its_now_form(group, name):
    entry = next(e for e in getattr(matchingAbi, group) if e.get("name") == name)
    assert (signature_of(entry), selector_of(entry)) == (CHANGED[name]["signature"], CHANGED[name]["now"])


def test_the_generation_signals_are_the_selectors_the_runner_reads():
    version = next(e for e in matchingAbi.pox if e.get("name") == "VERSION")
    matching_fn = next(e for e in matchingAbi.pricing if e.get("name") == "matching")
    assert selector_of(version) == SELECTORS["signals"]["version"]["selector"]
    assert selector_of(matching_fn) == SELECTORS["signals"]["matching"]["selector"]
    assert set(matchingContract.V2_ADD_ABI) == {a["value"] for a in SELECTORS["signals"]["version"]["answers"]}


# ------------------------------------------------------------- helpers

def word_of(e):
    """The reader's list word of a fixture entry (spec/matching.md 3)."""
    return (int(e["node"], 16) << 96 | e["score"] << 80 | int(e["fit"]) << 73 | int(e["match"]) << 72
            | e["listedOrdinal"] << 48 | e["dpRequestId"])


def page_of(stamp, entries, read):
    return {"roundStamp": stamp, "eligible": [word_of(e) for e in entries],
            "tips": [int(e["tipWei"]) for e in entries],
            "places": [matching.place_of(e["band"], e["index"]) for e in entries],
            "hOut": bytes.fromhex(read["listHash"][2:]), "matchFoundOut": read["matchFound"],
            "done": read["done"], "settled": read["settled"]}


def roll_bands(case):
    return {(e["node"], b["band"]) for b in case["roll"]["bands"] for e in b["entries"]}


def set_of(case):
    return case["parameterSets"][case["expected"]["parameterSetIndex"]]


def entries_of(rank_case):
    """The eligible entries of a matching-rank.json ranking case in roll
    order, decoded from the words its list holds."""
    expected = rank_case["expected"]
    base = int(expected["baseWei"]) if "baseWei" in expected else 0
    listed = sorted(expected.get("list", []), key=lambda e: (-e["band"], e["rollIndex"]))
    return [matching.decode_eligible(int(e["word"], 16), int(e["priceWei"]) - base,
                                     matching.place_of(e["band"], e["rollIndex"])) for e in listed]


def seed_of(rank_case):
    expected = rank_case["expected"]
    return bytes.fromhex(expected["seed"][2:])


def closed_step(block, round_block, step_blocks, lead_blocks):
    """The last step whose last block is `block` or earlier (4.5), as
    requestInfo answers it."""
    return max(0, matching.step_at(block + 1, round_block, step_blocks, lead_blocks) - 1)


def code_of(result):
    """Field 1 of a result string, the task code."""
    return int(result.split(":")[1])


# ------------------------------------------------------------- ranking.json

@pytest.mark.parametrize("case", RANKING["cases"], ids=[c["name"] for c in RANKING["cases"]])
def test_the_merged_read_is_the_reader_s(case):
    params = case["parameterSet"]
    read = case["candidates"]["read"]
    stamp = b"\x01" * 32
    pages = [page_of(stamp, read["eligible"], read)]
    beyond = case["candidates"].get("beyond")
    if beyond:
        pages.append(page_of(stamp, beyond["eligible"], dict(beyond, listHash=read["listHash"],
                                                             matchFound=read["matchFound"])))
    if not read["settled"]:
        with pytest.raises(matching.Unsettled):
            matching.merge_candidates(pages, params["maxSteps"])
        pages = [dict(page, settled=True) for page in pages]
    merged = matching.merge_candidates(pages, params["maxSteps"])
    assert "0x" + merged.list_hash.hex() == read["listHash"]
    assert merged.match_found == read["matchFound"]
    answered = read["eligible"] + (beyond["eligible"] if beyond else [])
    assert [(e.band, e.index) for e in merged.entries] == [(e["band"], e["index"]) for e in answered]
    bands = roll_bands(case)
    for e in merged.entries:
        assert (e.node, e.band) in bands, e.node
    schedule = matching.Schedule(merged.entries, bytes.fromhex(case["request"]["seed"][2:]), params["maxSteps"])
    for turn in case["turns"]:
        if not turn["eligible"] or not turn["done"]:
            continue
        step = schedule.mandated.index(turn["node"]) + 1 if turn["node"] in schedule.mandated else 0
        assert step == turn["mandateStep"], turn["node"]


def test_a_page_of_another_stamp_restarts_the_read():
    case = RANKING["cases"][0]
    read = case["candidates"]["read"]
    first = page_of(b"\x01" * 32, read["eligible"][:2], dict(read, done=False))
    second = page_of(b"\x02" * 32, read["eligible"][2:], read)
    with pytest.raises(matching.StampChanged):
        matching.merge_candidates([first, second], 8)


def test_an_unsettled_page_is_not_ranked_on():
    case = RANKING["cases"][0]
    read = dict(case["candidates"]["read"], settled=False)
    with pytest.raises(matching.Unsettled):
        matching.merge_candidates([page_of(b"\x01" * 32, read["eligible"], read)], 8)


def test_a_page_left_out_is_found_by_the_hash():
    case = RANKING["cases"][0]
    read = case["candidates"]["read"]
    with pytest.raises(ValueError):
        matching.merge_candidates([page_of(b"\x01" * 32, read["eligible"][1:], read)], 8)


def test_the_band_is_the_place_s_not_the_score_s():
    """An entry written into its band under another bandWidth stands in the
    band its place names: two scores of band 24 at a bandWidth of 1,000,
    one of them in band 12, the second matching entry of a read with
    maxSteps 2 ending the stop band there."""
    case = RANKING["cases"][0]
    first, second = (dict(e) for e in case["candidates"]["read"]["eligible"][:2])
    first.update(score=24_500, band=24, index=0, match=True)
    second.update(score=24_900, band=12, index=3, match=True)
    entries = [matching.decode_eligible(word_of(e), int(e["tipWei"]), matching.place_of(e["band"], e["index"]))
               for e in (first, second)]
    h, found, stop = matching.list_hash_of(entries, 2)
    read = {"listHash": "0x" + h.hex(), "matchFound": found, "done": True, "settled": True}
    merged = matching.merge_candidates([page_of(b"\x01" * 32, [first, second], read)], 2)
    assert [(e.band, e.index) for e in merged.entries] == [(24, 0), (12, 3)]
    assert merged.stop_band == stop == 12
    assert [e.node for e in matching.Schedule(merged.entries, b"\x00" * 32, 2).order] == [first["node"],
                                                                                          second["node"]]


# ------------------------------------------------------- matching-rank.json

@pytest.mark.parametrize("case", RANK["ranking"], ids=[c["name"] for c in RANK["ranking"]])
def test_the_ranking_case(case):
    expected = case["expected"]
    request = case["request"]
    params = set_of(case)
    assert keccak(bytes.fromhex(request["seedStamp"][2:]) + request["id"].to_bytes(32, "big")) == seed_of(case)
    assert matching.need_of(request["maxGflopsArg"]) == (expected["needGflops"], expected["ceilGflops"])
    assert "0x" + matching.template_key(expected["templateName"]).hex() == expected["templateKey"]
    assert "0x" + matching.image_key(request["metadata1"].split(":")[1]).hex() == expected["imageKey"]
    entries = entries_of(case)
    for e, listed in zip(entries, sorted(expected.get("list", []), key=lambda x: (-x["band"], x["rollIndex"]))):
        assert (e.node, e.band, e.fit, e.match, e.listed_ordinal, e.dp_request_id) == (
            listed["node"], listed["band"], listed["fit"], listed["match"], listed["listedOrdinal"],
            listed["dpRequestId"])
        assert "0x%064x" % matching.key_of(seed_of(case), e.node) == listed["key"]
    if not expected["ranked"]:
        assert entries == []
        return
    h, found, stop = matching.list_hash_of(entries, params["maxSteps"])
    assert ("0x" + h.hex(), found, stop) == (expected["listHash"], expected["matchFound"], expected["stopBand"])
    schedule = matching.Schedule(entries, seed_of(case), params["maxSteps"])
    assert [e.node for e in schedule.order] == [e["node"] for e in expected["list"]]
    assert schedule.position == {e["node"]: e["position"] for e in expected["list"]}
    assert schedule.mandated == expected["mandated"]
    for node, turn in expected["turns"].items():
        step = schedule.mandated.index(node) + 1 if node in schedule.mandated else 0
        assert step == turn["mandateStep"], node
    for block in expected["steps"]:
        assert matching.step_at(block["block"], expected["roundBlock"], params["stepBlocks"],
                                params["leadBlocks"]) == block["step"]
        assert closed_step(block["block"], expected["roundBlock"], params["stepBlocks"],
                           params["leadBlocks"]) == block["closedStep"]


@pytest.mark.parametrize("case", RANK["paging"], ids=[c["name"] for c in RANK["paging"]])
def test_the_paged_read(case):
    setup = RANK_CASES[case["setup"]]
    params = set_of(setup)
    expected = case["expected"]
    stamp = b"\x03" * 32
    pages = []
    for page in expected["pages"]:
        places = [matching.place_of(e["band"], e["index"]) for e in page["eligible"]]
        entries = [matching.decode_eligible(int(e["word"], 16), int(e["tipWei"]), place)
                   for e, place in zip(page["eligible"], places)]
        for e, listed in zip(entries, page["eligible"]):
            assert (e.band, e.index) == (listed["band"], listed["index"])
        pages.append({"roundStamp": stamp, "eligible": [int(e["word"], 16) for e in page["eligible"]],
                      "tips": [int(e["tipWei"]) for e in page["eligible"]], "places": places,
                      "hOut": bytes.fromhex(page["hOut"][2:]), "matchFoundOut": page["matchFoundOut"],
                      "done": page["done"], "settled": True})
        merged = matching.merge_candidates(pages, params["maxSteps"])
        assert merged.done == page["done"]
    assert "0x" + merged.list_hash.hex() == expected["listHash"]
    assert (merged.match_found, merged.stop_band) == (expected["matchFound"], expected["stopBand"])


def standings_of(case, nodes):
    found = {}
    for node in nodes:
        given = case["nodes"].get(node, {})
        found[node] = matching.Standing(given.get("score", matching.SCORE_MAX), given.get("canAnswer", True),
                                        given.get("lastFailureSlot", 0))
    return found


@pytest.mark.parametrize("case", RANK["approvals"], ids=[c["name"] for c in RANK["approvals"]])
def test_the_approval_rule(case):
    setup = RANK_CASES[case["setup"]]
    params = set_of(setup)
    round_block = setup["rounds"][setup["round"]]["block"]
    schedule = matching.Schedule(entries_of(setup), seed_of(setup), params["maxSteps"])
    claims = {c["node"]: matching.ClaimView(c["block"], case["nodes"].get(c["node"], {}).get("approvable", True), 0)
              for c in case["claims"]}
    standings = standings_of(case, set(schedule.mandated) | set(claims))
    if case.get("developerMinScore") is not None:
        min_score = case["developerMinScore"]
    else:
        min_score = matching.DEFAULT_MIN_SCORE if case["minimumOn"] else 0
    closed = closed_step(case["readBlock"], round_block, params["stepBlocks"], params["leadBlocks"])
    decision = matching.decide_approval(schedule.mandated, schedule.position, claims, standings, (), closed,
                                        min_score, case["recentFailureSlots"], case["slotNow"], round_block,
                                        params["stepBlocks"], params["leadBlocks"])
    expected = case["expected"]
    assert closed == expected["closedStep"]
    assert decision.approve == expected["approve"]
    assert decision.rule == expected["rule"]
    if "inTime" in expected:
        assert decision.in_time == expected["inTime"]
    assert decision.wait == expected.get("wait", False)


def test_an_excluded_mandated_node_is_passed_over_at_once():
    case = next(c for c in RANK["approvals"] if c["name"] == "wait-for-n1-step")
    setup = RANK_CASES[case["setup"]]
    params = set_of(setup)
    schedule = matching.Schedule(entries_of(setup), seed_of(setup), params["maxSteps"])
    n1, n5 = schedule.mandated[0], schedule.mandated[1]
    claims = {n1: matching.ClaimView(1001, True, 0), n5: matching.ClaimView(1001, True, 0)}
    standings = standings_of(case, set(schedule.mandated) | set(claims))
    decision = matching.decide_approval(schedule.mandated, schedule.position, claims, standings, {n1}, 0, 0, 14,
                                        case["slotNow"], 1000, params["stepBlocks"], params["leadBlocks"])
    assert (decision.approve, decision.rule) == (n5, 1)


def test_claims_below_the_minimum_are_named_when_none_stands():
    case = next(c for c in RANK["approvals"] if c["name"] == "recent-failure-taken-last")
    setup = RANK_CASES[case["setup"]]
    params = set_of(setup)
    schedule = matching.Schedule(entries_of(setup), seed_of(setup), params["maxSteps"])
    n1 = schedule.mandated[0]
    claims = {n1: matching.ClaimView(1001, True, 0)}
    standings = {n: matching.Standing(4999 if n == n1 else matching.SCORE_MAX, True, 0) for n in schedule.mandated}
    decision = matching.decide_approval(schedule.mandated, schedule.position, claims, standings, (), 6, 5000, 14,
                                        case["slotNow"], 1000, params["stepBlocks"], params["leadBlocks"])
    assert decision == matching.Decision(None, None, None, False, [n1])


@pytest.mark.parametrize("case", RANK["quotes"], ids=[c["name"] for c in RANK["quotes"]])
def test_the_bid_a_raise_sends(case):
    expected = case["expected"]
    if "sendBidWei" not in expected:
        pytest.skip("a quote for terms names no bid in force")
    assert matching.send_bid(int(expected["minBidWei"]), int(expected["bidWei"])) == int(expected["sendBidWei"])


def quote_of(case):
    expected = case["expected"]
    return matching.Quote(b"\x00" * 32, expected["counted"], expected["canClaimNow"], int(expected["minBidWei"]),
                          int(expected["baseNowWei"]), int(expected["bidWei"]), 0)


@pytest.mark.parametrize("name", ["quote-raise-example", "quote-with-ceiling-min-score", "quote-fallen-price"])
def test_a_quote_no_claim_can_come_at_is_raised_to_its_bid(name):
    case = next(c for c in RANK["quotes"] if c["name"] == name)
    decision = matching.decide_raise(quote_of(case), 0, 0, False, 1, 8, 0, 5, 10**19)
    assert decision == matching.RaiseDecision(matching.RAISE, int(case["expected"]["sendBidWei"]), decision.reason)


def test_a_quote_with_claimable_nodes_waits():
    case = next(c for c in RANK["quotes"] if c["name"] == "quote-without-ceiling")
    assert matching.decide_raise(quote_of(case), 0, 0, False, 1, 8, 0, 5, 10**19).action == matching.WAIT
    assert matching.decide_raise(quote_of(case), 1, 0, False, 1, 8, 0, 5, 10**19).action == matching.WAIT
    raised = matching.decide_raise(quote_of(case), 2, 0, False, 9, 8, 0, 5, 10**19)
    assert raised.action == matching.RAISE and raised.bid_wei == int(case["expected"]["sendBidWei"])


# ------------------------------------------------------- result-fields.json

@pytest.mark.parametrize("vector", FIELDS["accepted"], ids=[v["name"] for v in FIELDS["accepted"]])
def test_the_three_fields_are_read(vector):
    expected = vector["expected"]
    assert code_of(vector["result"]) == expected["code"]
    assert matching.result_fields(vector["result"]) == matching.ResultFields(
        int(expected["landedAt"]), int(expected["ranUntil"]), expected["slClass"])


@pytest.mark.parametrize("vector", FIELDS["refused"], ids=[v["name"] for v in FIELDS["refused"]])
def test_the_three_fields_are_not_read(vector):
    assert code_of(vector["result"]) == vector["expected"]["code"]
    assert matching.result_fields(vector["result"]) is None


@pytest.mark.parametrize("vector", FIELDS["stored"], ids=[v["name"] for v in FIELDS["stored"]])
def test_the_stored_result_s_grammar(vector):
    expected = vector["expected"]
    read = matching.read_stored(vector["stored"], FIELDS["transaction"]["orderId"])
    assert read.status == expected["status"]
    if expected["transaction"]:
        assert (read.order_id, read.signer) == (expected["orderId"], expected["signer"])
    else:
        assert read == matching.StoredRead(expected["status"], None, None, None)
    assert read.code == (expected["code"] if expected["status"] == matching.STORED_DECODED else None)


def test_the_grammar_s_vectors_cover_every_status():
    assert {v["expected"]["status"] for v in FIELDS["stored"]} == {
        matching.STORED_DECODED, matching.STORED_NOT_V3, matching.STORED_NO_TRANSACTION, matching.STORED_OTHER_ORDER,
        matching.STORED_NO_CODE}
    assert len(FIELDS["stored"]) == 53


@pytest.mark.parametrize("vector", FIELDS["accepted"] + FIELDS["refused"],
                         ids=[v["name"] for v in FIELDS["accepted"] + FIELDS["refused"]])
def test_the_stored_form_of_each_result_is_decoded_for_its_order(vector):
    read = matching.read_stored(vector["stored"], FIELDS["transaction"]["orderId"])
    assert read.status == matching.STORED_DECODED and read.code == vector["expected"]["code"]
    other = matching.read_stored(vector["stored"], FIELDS["transaction"]["orderId"] + 1)
    assert other.status == matching.STORED_OTHER_ORDER and other.order_id == FIELDS["transaction"]["orderId"]


@pytest.mark.parametrize("vector", FIELDS["accepted"] + FIELDS["refused"],
                         ids=[v["name"] for v in FIELDS["accepted"] + FIELDS["refused"]])
def test_the_stored_result_carries_its_result_string(vector):
    runner = EthernityCloudRunner("LOCAL", "LOCAL")
    runner.protocol_abi = polygon_abi["abi"]
    stored = runner.parse_order_result(vector["stored"])
    parsed = runner.parse_transaction_bytes(runner.hex_to_bytes(stored["transaction_bytes"]))
    assert parsed["result"] == vector["result"]
    assert parsed["order_id"] == FIELDS["transaction"]["orderId"]
