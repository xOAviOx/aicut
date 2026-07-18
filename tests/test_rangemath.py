"""Range math edge cases + remap/inverse — the most safety-critical module."""

from __future__ import annotations

import pytest

from aicut import rangemath as rm


class TestNormalize:
    def test_merges_overlapping(self):
        assert rm.normalize([(0, 2), (1, 3)]) == [(0, 3)]

    def test_merges_adjacent(self):
        assert rm.normalize([(0, 1), (1, 2)]) == [(0, 2)]

    def test_drops_zero_and_negative(self):
        assert rm.normalize([(5, 5), (3, 2), (1, 2)]) == [(1, 2)]

    def test_sorts_unsorted(self):
        assert rm.normalize([(5, 6), (1, 2), (3, 4)]) == [(1, 2), (3, 4), (5, 6)]

    def test_empty(self):
        assert rm.normalize([]) == []

    def test_nested_absorbed(self):
        assert rm.normalize([(0, 10), (2, 3), (4, 5)]) == [(0, 10)]


class TestSubtract:
    def test_middle_hole(self):
        assert rm.subtract([(0, 10)], [(3, 5)]) == [(0, 3), (5, 10)]

    def test_left_edge(self):
        assert rm.subtract([(0, 10)], [(0, 3)]) == [(3, 10)]

    def test_right_edge(self):
        assert rm.subtract([(0, 10)], [(7, 10)]) == [(0, 7)]

    def test_out_of_bounds_noop(self):
        assert rm.subtract([(0, 10)], [(20, 30)]) == [(0, 10)]

    def test_full_removal(self):
        assert rm.subtract([(0, 10)], [(0, 10)]) == []

    def test_multiple_holes(self):
        assert rm.subtract([(0, 10)], [(2, 3), (5, 6)]) == [(0, 2), (3, 5), (6, 10)]

    def test_nested_cut_larger_than_keep(self):
        assert rm.subtract([(2, 4)], [(0, 10)]) == []


class TestIntersect:
    def test_partial(self):
        assert rm.intersect([(0, 10)], [(5, 15)]) == [(5, 10)]

    def test_disjoint(self):
        assert rm.intersect([(0, 5)], [(10, 15)]) == []

    def test_multi(self):
        assert rm.intersect([(0, 10)], [(1, 2), (3, 4), (20, 30)]) == [(1, 2), (3, 4)]

    def test_identity(self):
        assert rm.intersect([(0, 10)], [(0, 10)]) == [(0, 10)]


class TestInvertPadClamp:
    def test_invert(self):
        assert rm.invert([(2, 4)], 10) == [(0, 2), (4, 10)]

    def test_invert_empty(self):
        assert rm.invert([], 10) == [(0, 10)]

    def test_invert_full(self):
        assert rm.invert([(0, 10)], 10) == []

    def test_pad_merges(self):
        # two spans 0.1 apart, padded 0.1 each side -> touch and merge
        result = rm.pad([(0, 1), (1.1, 2)], 0.1, 10)
        assert len(result) == 1
        assert result[0][0] == pytest.approx(0.0)
        assert result[0][1] == pytest.approx(2.1)

    def test_pad_clamps_to_duration(self):
        assert rm.pad([(0, 10)], 1.0, 10) == [(0, 10)]

    def test_clamp(self):
        assert rm.clamp([(-5, 5), (8, 20)], 0, 10) == [(0, 5), (8, 10)]


class TestDropShort:
    def test_drops_below_min(self):
        assert rm.drop_short([(0, 0.1), (1, 5)], 0.25) == [(1, 5)]

    def test_keeps_exactly_min(self):
        assert rm.drop_short([(0, 0.25)], 0.25) == [(0, 0.25)]


class TestTotal:
    def test_sum(self):
        assert rm.total([(0, 10), (20, 30)]) == 20

    def test_overlap_counted_once(self):
        assert rm.total([(0, 10), (5, 15)]) == 15


class TestRemap:
    keep = [(0.0, 10.0), (20.0, 30.0)]

    def test_before_first(self):
        assert rm.remap_time(0, self.keep) == 0

    def test_inside_first(self):
        assert rm.remap_time(5, self.keep) == 5

    def test_inside_cut_collapses_to_boundary(self):
        assert rm.remap_time(15, self.keep) == 10

    def test_inside_second(self):
        assert rm.remap_time(25, self.keep) == 15

    def test_after_all(self):
        assert rm.remap_time(100, self.keep) == 20

    def test_inverse_is_left_inverse(self):
        # points strictly interior to kept spans (boundary times between a cut
        # and a keep are intentionally ambiguous under the inverse map)
        for t in [0.0, 3.3, 9.9, 20.1, 24.5, 29.99]:
            out = rm.remap_time(t, self.keep)
            back = rm.inverse_remap(out, self.keep)
            assert back == pytest.approx(t, abs=1e-6)

    def test_inverse_empty(self):
        assert rm.inverse_remap(5, []) == 0

    def test_inverse_clamps_beyond(self):
        assert rm.inverse_remap(1000, self.keep) == 30.0


class TestContainsNext:
    keep = [(0.0, 10.0), (20.0, 30.0)]

    def test_contains(self):
        assert rm.contains(self.keep, 5)
        assert not rm.contains(self.keep, 15)

    def test_next_keep_start(self):
        assert rm.next_keep_start(self.keep, 12) == 20
        assert rm.next_keep_start(self.keep, 25) is None
