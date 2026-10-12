import pytest

from owd.render import joined_duration, xfade_offsets
from owd.timeline import chapter_shots, choose_cuts, plan_shots, shot_lengths, snap_fade
from owd.words import Word
from tests.helpers import words_at


def test_cuts_prefer_a_nearby_sentence_end_but_keep_shots_even():
    near = words_at("one two three four five. six seven eight nine ten eleven twelve.", step=0.5)
    # The middle is about 2.98 s; the sentence ends at about 2.48 s, close enough to win
    assert choose_cuts(near, 2) == [pytest.approx((near[4].end + near[5].start) / 2)]
    far = words_at("one two three four. five six seven eight nine ten eleven twelve.", step=0.5)
    # Here the sentence ends a whole second early, so the cut stays in the middle
    assert choose_cuts(far, 2) == [pytest.approx((far[5].end + far[6].start) / 2)]


def test_cuts_keep_every_shot_at_least_min_shot_long():
    words = words_at("a b c d e f g h", step=0.5)  # 4 s of narration
    cuts = choose_cuts(words, 10, min_shot=1.0)
    bounds = [0.0, *cuts, words[-1].end]
    assert all(b - a >= 1.0 for a, b in zip(bounds, bounds[1:]))
    assert choose_cuts(words, 1) == [] and choose_cuts([Word("solo", 0, 1)], 3) == []


def test_snap_fade_uses_an_even_number_of_frames():
    assert snap_fade(0.6) * 30 == pytest.approx(18)
    assert snap_fade(0.5) * 30 == pytest.approx(16)  # 15 frames would leave half a frame
    assert snap_fade(0.0) * 30 == pytest.approx(2)


def test_shot_lengths_centre_each_crossfade_on_its_cut_in_whole_frames():
    cuts, total, fade = [9.206, 12.95, 21.0], 27.6, 0.6
    lengths = shot_lengths(cuts, total, fade)
    assert all(abs(length * 30 - round(length * 30)) < 1e-6 for length in lengths)
    assert joined_duration(lengths, fade) == pytest.approx(total, abs=1 / 30)
    for offset, cut in zip(xfade_offsets(lengths, fade), cuts):
        assert offset + fade / 2 == pytest.approx(cut, abs=1 / 60 + 1e-6)


def test_shot_lengths_do_not_drift_over_a_long_video():
    cuts = [7.123 * k + 0.0137 * k * k for k in range(1, 120)]
    lengths = shot_lengths(cuts, cuts[-1] + 6.0, 0.6)
    offsets = xfade_offsets(lengths, 0.6)
    assert max(abs(offset + 0.3 - cut) for offset, cut in zip(offsets, cuts)) <= 1 / 60 + 1e-6


def test_plan_shots_cuts_at_every_scene_and_splits_long_scenes():
    first = words_at("one two three four five six", step=0.5)  # 0 - 2.95 s
    second = words_at("a b c d e f g h i j k l m n o p q r s t", start=3.5, step=0.5)  # 3.5 - 13.45 s
    words = first + second
    cuts, scenes = plan_shots(words, [(0, 6), (6, 26)], total=14.0, max_shot=4.0)
    boundary = (first[-1].end + second[0].start) / 2
    assert cuts[0] == pytest.approx(boundary)
    assert scenes == [0, 1, 1, 1]  # 10.5 s second scene in three shots of about 3.5 s
    assert all(b > a for a, b in zip(cuts, cuts[1:]))
    gaps = {(w1.end + w2.start) / 2 for w1, w2 in zip(second, second[1:])}
    assert all(any(abs(cut - gap) < 1e-6 for gap in gaps) for cut in cuts[1:])


def test_plan_shots_single_scene_short_enough_is_one_shot():
    words = words_at("only a few words", step=0.5)
    assert plan_shots(words, [(0, 4)], total=2.0, max_shot=5.0) == ([], [0])


def test_chapter_shots_crossfade_inside_chapters_and_meet_exactly_at_boundaries():
    # Shots 0-2 belong to scenes 0, 1, 1 (chapter 0); shot 3 to scene 2 (chapter 1)
    plan = chapter_shots([2.0, 4.0, 6.0], [0, 1, 1, 2], [0, 0, 1], total=8.0, fade=0.6)
    assert [(start, end) for start, end, _ in plan] == [(0.0, 6.0), (6.0, 8.0)]
    assert plan[0][2] == pytest.approx([2.3, 2.6, 2.3]) and plan[1][2] == pytest.approx([2.0])
    for start, end, lengths in plan:  # each chapter's crossfaded shots fill it exactly
        assert joined_duration(lengths, 0.6) == pytest.approx(end - start)
