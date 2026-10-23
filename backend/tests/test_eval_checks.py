from memoria.eval.checks import (
    CheckResult,
    assets_verified,
    canary_absent,
    leads_with_change,
    mentions_keywords,
    objection_superseded,
    pitch_order_changed,
    slot_recall,
)
from memoria.models import AssetRef, Slot, SlotBoard


def board_with(**statuses: str) -> SlotBoard:
    board = SlotBoard()
    for name, status in statuses.items():
        board.slots[name] = Slot(value="x" if status != "rep_unsure" else None, status=status)
    return board


def strategy(*titles: str, shuffled: bool = False) -> dict:
    items = [{"order": i + 1, "segment": t} for i, t in enumerate(titles)]
    return {"pitch_sequence": list(reversed(items)) if shuffled else items}


class TestSlotRecall:
    def test_all_expected_slots_filled_passes(self):
        board = board_with(pain="confirmed", metrics="rep_unsure")
        result = slot_recall(board, {"pain": "slow", "metrics": "mttr", "champion": None})
        assert result.passed and result.name == "slot_recall"

    def test_null_fact_sheet_slots_are_not_expected(self):
        result = slot_recall(SlotBoard(), {"pain": None})
        assert result.passed

    def test_open_and_conflict_slots_do_not_count(self):
        board = board_with(pain="confirmed", metrics="conflict", champion="open")
        result = slot_recall(board, {"pain": "a", "metrics": "b", "champion": "c"}, threshold=0.5)
        assert not result.passed
        assert "metrics" in result.detail and "champion" in result.detail

    def test_threshold_boundary_is_inclusive(self):
        board = board_with(
            pain="confirmed", metrics="confirmed", champion="confirmed", objections="confirmed"
        )
        facts = {"pain": "a", "metrics": "b", "champion": "c", "objections": "d", "competition": "e"}
        assert slot_recall(board, facts, threshold=0.8).passed
        assert not slot_recall(board, facts, threshold=0.81).passed

    def test_slot_missing_from_board_counts_as_missed(self):
        board = SlotBoard(slots={})
        assert not slot_recall(board, {"pain": "a"}).passed


class TestMentionsKeywords:
    def test_case_insensitive_hit(self):
        assert mentions_keywords("They worry about SOC 2 scope", ["soc 2"]).passed

    def test_no_hit_fails_with_keywords_in_detail(self):
        result = mentions_keywords("nothing relevant", ["egress", "latency"])
        assert not result.passed and "egress" in result.detail

    def test_min_hits(self):
        text = "egress costs are high"
        assert not mentions_keywords(text, ["egress", "latency"], min_hits=2).passed
        assert mentions_keywords(text + " and latency", ["egress", "latency"], min_hits=2).passed

    def test_empty_keywords_fails_rather_than_passing_vacuously(self):
        assert not mentions_keywords("anything", []).passed

    def test_custom_name(self):
        assert mentions_keywords("a", ["a"], name="flags_conflict").name == "flags_conflict"


class TestPitchOrderChanged:
    def test_different_order_passes(self):
        assert pitch_order_changed(strategy("A", "B", "C"), strategy("B", "A", "C")).passed

    def test_same_order_fails(self):
        assert not pitch_order_changed(strategy("A", "B"), strategy("A", "B")).passed

    def test_uses_order_field_not_list_position(self):
        assert not pitch_order_changed(strategy("A", "B"), strategy("A", "B", shuffled=True)).passed

    def test_titles_compared_case_and_whitespace_insensitively(self):
        assert not pitch_order_changed(strategy("Cost case"), strategy(" cost CASE ")).passed

    def test_missing_pitch_sequence_fails_with_reason(self):
        result = pitch_order_changed({}, strategy("A"))
        assert not result.passed and "before" in result.detail


class TestObjectionSuperseded:
    def test_superseded_in_account_objections(self):
        snap = {"/accounts/acme/objections.md": "| O1 | price | superseded 2026-10-23 by O2 |"}
        assert objection_superseded(snap, "acme").passed

    def test_path_without_leading_slash(self):
        snap = {"accounts/acme/objections.md": "Superseded by O4"}
        assert objection_superseded(snap, "acme").passed

    def test_other_account_does_not_count(self):
        snap = {"/accounts/other/objections.md": "superseded"}
        assert not objection_superseded(snap, "acme").passed

    def test_slug_prefix_does_not_match(self):
        snap = {"/accounts/acme-corp/objections.md": "superseded"}
        assert not objection_superseded(snap, "acme").passed

    def test_file_present_without_marker_fails(self):
        snap = {"/accounts/acme/objections.md": "| O1 | price | open |"}
        result = objection_superseded(snap, "acme")
        assert not result.passed and "superseded" in result.detail

    def test_missing_file_fails(self):
        assert not objection_superseded({}, "acme").passed


class TestCanaryAbsent:
    def test_clean_texts_pass(self):
        assert canary_absent(["hello", "world"], ["CANARY-B-1a2b3c4d"]).passed

    def test_leak_fails_and_names_canary(self):
        result = canary_absent(["x CANARY-B-1a2b3c4d y"], ["CANARY-B-1a2b3c4d"])
        assert not result.passed and "CANARY-B-1a2b3c4d" in result.detail

    def test_no_foreign_canaries_passes(self):
        assert canary_absent(["anything"], []).passed


class TestAssetsVerified:
    def ref(self, verdict: str) -> AssetRef:
        return AssetRef(asset_type="deck", title="t", verdict=verdict)

    def test_all_pass(self):
        assert assets_verified([self.ref("pass"), self.ref("pass")]).passed

    def test_needs_review_fails(self):
        result = assets_verified([self.ref("pass"), self.ref("needs_human_review")])
        assert not result.passed and "1" in result.detail

    def test_no_assets_fails(self):
        assert not assets_verified([]).passed


class TestLeadsWithChange:
    def test_leads(self):
        assert leads_with_change("Since our last session: the CFO changed.").passed

    def test_leading_whitespace_tolerated(self):
        assert leads_with_change("\n  Since our last session, things moved.").passed

    def test_buried_mention_fails(self):
        assert not leads_with_change("Here is the plan. Since our last session: x").passed

    def test_empty_fails(self):
        assert not leads_with_change("").passed


def test_check_result_defaults_to_not_errored():
    assert CheckResult("n", True, "d").errored is False
