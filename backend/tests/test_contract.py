from memoria.chain_prompts import SLOT_NAMES
from memoria.models import SlotBoard, SlotUpdate
from memoria.ports import diff_snapshots


def test_new_board_has_every_slot_open():
    board = SlotBoard()
    assert list(board.slots) == SLOT_NAMES
    assert all(s.status == "open" and s.value is None for s in board.slots.values())


def test_apply_update_replaces_slot_and_render_shows_it():
    board = SlotBoard()
    board.apply([SlotUpdate(slot="pain", value="manual reconciliation", status="confirmed",
                            evidence_quote="they reconcile by hand")])
    assert board.slots["pain"].value == "manual reconciliation"
    assert "pain: [confirmed] manual reconciliation" in board.render()
    assert "metrics: [open] -" in board.render()


def test_diff_snapshots_reports_added_modified_removed_in_path_order():
    before = {"/a.md": "1", "/b.md": "old", "/c.md": "gone"}
    after = {"/a.md": "1", "/b.md": "new", "/d.md": "fresh"}
    changes = diff_snapshots(before, after)
    assert [(c.path, c.change) for c in changes] == [
        ("/b.md", "modified"), ("/c.md", "removed"), ("/d.md", "added"),
    ]
    assert changes[0].before == "old" and changes[0].after == "new"


def test_diff_of_identical_snapshots_is_empty():
    assert diff_snapshots({"/x": "y"}, {"/x": "y"}) == []
