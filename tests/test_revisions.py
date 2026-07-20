"""Revision / undo model + persistence round-trip."""

from __future__ import annotations

from aicut.models import Anchor, CutRanges, EditPlan, Trim
from aicut.project import ProjectStore


def _seed(store: ProjectStore, transcript):
    project = store.create("test.mp4", name="test")
    store.finalize_transcript(project.id, transcript)
    return store.get(project.id)


def test_finalize_seeds_original_revision(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    assert project.transcript_status == "ready"
    assert len(project.revisions) == 1
    assert project.revisions[0].label == "Original"
    assert project.head_revision_id == project.revisions[0].id


def test_append_revision_advances_head(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    plan = EditPlan(actions=[CutRanges(ranges=[(0, 2)])], notes="cut intro")
    project, rev = store.append_revision(project.id, plan, "Manual: cut intro")
    assert len(project.revisions) == 2
    assert project.head_revision_id == rev.id
    assert "Manual: cut intro" in rev.label
    assert rev.notes == "cut intro"


def test_undo_redo_moves_head(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    r0 = project.revisions[0].id
    project, r1 = store.append_revision(
        project.id, EditPlan(actions=[CutRanges(ranges=[(0, 2)])]), "edit1"
    )
    project = store.undo(project.id)
    assert project.head_revision_id == r0
    project = store.redo(project.id)
    assert project.head_revision_id == r1.id


def test_edit_after_undo_drops_tail(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    project, r1 = store.append_revision(
        project.id, EditPlan(actions=[CutRanges(ranges=[(0, 2)])]), "edit1"
    )
    project, r2 = store.append_revision(
        project.id, EditPlan(actions=[CutRanges(ranges=[(2, 3)])]), "edit2"
    )
    # undo back to r1, then a new edit should drop r2
    project = store.undo(project.id)
    assert project.head_revision_id == r1.id
    project, r3 = store.append_revision(
        project.id, EditPlan(actions=[CutRanges(ranges=[(5, 6)])]), "edit3"
    )
    ids = [r.id for r in project.revisions]
    assert r2.id not in ids
    assert ids[-1] == r3.id
    assert len(project.revisions) == 3  # original, r1, r3


def test_manual_edits_group_into_one_entry(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    # two grouped manual edits in quick succession fold into one revision
    project, r1 = store.append_revision(
        project.id, EditPlan(actions=[CutRanges(ranges=[(0, 1)])]), "cut", group_key="manual"
    )
    project, r2 = store.append_revision(
        project.id, EditPlan(actions=[CutRanges(ranges=[(1, 2)])]), "cut", group_key="manual"
    )
    assert r2.id == r1.id  # folded into the same revision
    assert len(project.revisions) == 2  # Original + one grouped entry
    assert "grouped" in project.revisions[-1].label
    # both cuts are reflected in the folded revision
    from aicut import rangemath as rm

    assert not rm.contains(project.revisions[-1].edl.keep, 0.5)
    assert not rm.contains(project.revisions[-1].edl.keep, 1.5)
    # undo removes the whole group at once
    project = store.undo(project.id)
    assert project.head_revision_id == project.revisions[0].id


def test_non_grouped_edits_stay_separate(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    # no group_key (e.g. one-click / AI) → distinct entries
    store.append_revision(project.id, EditPlan(actions=[CutRanges(ranges=[(0, 1)])]), "a")
    project, _ = store.append_revision(
        project.id, EditPlan(actions=[CutRanges(ranges=[(1, 2)])]), "b"
    )
    assert len(project.revisions) == 3  # Original + two separate edits


def test_undo_at_start_is_noop(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    head = project.head_revision_id
    project = store.undo(project.id)
    assert project.head_revision_id == head


def test_goto_revision_time_travels(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    r0 = project.revisions[0].id
    project, r1 = store.append_revision(
        project.id, EditPlan(actions=[CutRanges(ranges=[(0, 2)])]), "edit1"
    )
    project = store.goto_revision(project.id, r0)
    assert project.head_revision_id == r0


def test_persistence_round_trip(isolated_home, simple_transcript):
    store = ProjectStore()
    project = _seed(store, simple_transcript)
    store.append_revision(
        project.id,
        EditPlan(actions=[Trim(mode="before", anchor=Anchor(kind="time", value=4.0))]),
        "trim",
    )
    # a fresh store instance must read the same state from disk
    store2 = ProjectStore()
    loaded = store2.get(project.id)
    assert loaded is not None
    assert len(loaded.revisions) == 2
    transcript = store2.get_transcript(project.id)
    assert transcript is not None
    assert len(transcript.segments) == len(simple_transcript.segments)


def test_settings_mirror_head(isolated_home, simple_transcript):
    from aicut.models import SetAspect

    store = ProjectStore()
    project = _seed(store, simple_transcript)
    project, _ = store.append_revision(
        project.id, EditPlan(actions=[SetAspect(aspect="9:16")]), "vertical"
    )
    assert project.settings.aspect == "9:16"
    project = store.undo(project.id)
    assert project.settings.aspect == "source"
