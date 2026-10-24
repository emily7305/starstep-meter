import math

import numpy as np
import pytest

from backend.analysis.grid_fit import MIN_BEATS
from backend.analysis.tempo_edit import (
    TempoEditError,
    TrackedTimes,
    keep_manual_segments,
    merge,
    set_anchor,
    set_bpm,
    split,
)
from backend.schema.models import AudioSource, TempoSegment, TimingReport, Trim

BPM_TOLERANCE = 0.01
ANCHOR_TOLERANCE_MS = 0.01

# a steady stretch for the "too few beats" cases, 125 bpm
STEADY_BEATS = 40
STEADY_PERIOD_MS = 480.0


def _seg(start, end, bpm=120.0, anchor=None, confidence=0.9, source="auto"):
    return TempoSegment(
        start_ms=start, end_ms=end, bpm=bpm, anchor_ms=start if anchor is None else anchor, confidence=confidence, source=source
    )


def _hand(start, end, bpm, confidence=None):
    return _seg(start, end, bpm=bpm, anchor=start + 20.0, confidence=confidence, source="manual")


def _three():
    # three different tempos, so a half beat or a beat period differs per segment
    return [
        _seg(1000.0, 5000.0, bpm=120.0),
        _seg(5000.0, 9000.0, bpm=60.0),
        _seg(9000.0, 13000.0, bpm=240.0),
    ]


def _fresh():
    # anchors off the segment starts, so a moved grid would show
    return [
        _seg(1000.0, 4000.0, bpm=100.0, anchor=1010.0),
        _seg(4000.0, 8000.0, bpm=110.0, anchor=4020.0),
        _seg(8000.0, 12000.0, bpm=140.0, anchor=8030.0),
    ]


def _tracked(times):
    return TrackedTimes(times_ms=times, is_downbeat=np.arange(len(times)) % 4 == 0, downbeats_known=True)


def _report(segments):
    return TimingReport(
        source=AudioSource(
            filename="click.wav", sha256="0" * 64, duration_ms=30000.0, sample_rate=44100, codec="pcm_f32le", decoder_padding_samples=0
        ),
        trim=Trim(start_ms=segments[0].start_ms, end_ms=segments[-1].end_ms),
        tempo_map=segments,
    )


def _assert_valid_map(segments):
    # model_copy skips validation, so check the ordering by hand and let the report check contiguity
    assert all(s.start_ms < s.end_ms for s in segments)
    _report(segments)


# --- set_bpm and set_anchor ---


def test_set_bpm_makes_the_segment_manual_and_keeps_its_anchor_and_edges():
    segments = _three()

    out = set_bpm(segments, 1, 90.0)

    assert len(out) == 3
    assert out[1].bpm == 90.0
    assert out[1].source == "manual"
    assert out[1].confidence is None
    assert (out[1].start_ms, out[1].end_ms, out[1].anchor_ms) == (5000.0, 9000.0, 5000.0)
    assert out[0] == segments[0]
    assert out[2] == segments[2]


def test_set_anchor_makes_the_segment_manual_and_keeps_its_bpm_and_edges():
    segments = _three()

    out = set_anchor(segments, 1, 6250.0)

    assert len(out) == 3
    assert out[1].anchor_ms == 6250.0
    assert out[1].source == "manual"
    assert out[1].confidence is None
    assert (out[1].start_ms, out[1].end_ms, out[1].bpm) == (5000.0, 9000.0, 60.0)
    assert out[0] == segments[0]
    assert out[2] == segments[2]


@pytest.mark.parametrize(
    "index, anchor_ms",
    [
        (0, 3000.0),
        (0, 500.0),
        (0, 5500.0),
        (1, 4200.0),
        (1, 10000.0),
        (2, 8750.0),
        (2, 13250.0),
    ],
    ids=[
        "inside",
        "one-beat-before-start",
        "one-beat-after-end",
        "slow-slack-is-longer",
        "slow-one-beat-after-end",
        "fast-one-beat-before-start",
        "fast-one-beat-after-end",
    ],
)
def test_anchor_within_a_beat_of_the_segment_is_accepted(index, anchor_ms):
    out = set_anchor(_three(), index, anchor_ms)

    assert out[index].anchor_ms == anchor_ms


@pytest.mark.parametrize(
    "index, anchor_ms",
    [
        (0, 499.9),
        (0, 5500.1),
        (1, 3999.9),
        (1, 10000.1),
        (2, 8749.9),
        (2, 13250.1),
    ],
    ids=["before-start", "after-end", "slow-before-start", "slow-after-end", "fast-before-start", "fast-after-end"],
)
def test_anchor_further_than_a_beat_from_the_segment_is_refused(index, anchor_ms):
    with pytest.raises(TempoEditError):
        set_anchor(_three(), index, anchor_ms)


CALLS = {
    "set_bpm": lambda segments: set_bpm(segments, 1, 90.0),
    "set_anchor": lambda segments: set_anchor(segments, 1, 6000.0),
    "split": lambda segments: split(segments, 3000.0),
    "merge": lambda segments: merge(segments, 1),
}


@pytest.mark.parametrize("call", CALLS.values(), ids=CALLS.keys())
def test_edits_return_a_new_list_and_leave_the_input_alone(call):
    segments = _three()
    before = [s.model_copy() for s in segments]

    out = call(segments)

    assert out is not segments
    assert segments == before


AT_INDEX = {
    "set_bpm": lambda segments, index: set_bpm(segments, index, 90.0),
    "set_anchor": lambda segments, index: set_anchor(segments, index, 6000.0),
    "merge": lambda segments, index: merge(segments, index),
}


@pytest.mark.parametrize("index", [-1, 3, 10], ids=["negative", "past-the-end", "far-past-the-end"])
@pytest.mark.parametrize("call", AT_INDEX.values(), ids=AT_INDEX.keys())
def test_a_bad_index_is_refused(call, index):
    # -1 must not wrap around to the last segment
    with pytest.raises(TempoEditError):
        call(_three(), index)


# --- split ---


def test_split_makes_two_manual_halves_that_meet_at_the_rounded_time():
    segments = _three()

    out = split(segments, 6000.12345)

    left, right = out[1], out[2]
    assert len(out) == 4
    assert left.end_ms == right.start_ms == 6000.123
    assert (left.start_ms, right.end_ms) == (5000.0, 9000.0)
    assert left.source == right.source == "manual"
    assert out[0] == segments[0]
    assert out[3] == segments[2]
    _assert_valid_map(out)


@pytest.mark.parametrize(
    "at_ms, index",
    [
        (1250.0, 0),
        (4750.0, 0),
        (5500.0, 1),
        (8500.0, 1),
        (9130.0, 2),
    ],
    ids=[
        "half-a-beat-from-start",
        "half-a-beat-from-end",
        "slow-half-a-beat-from-start",
        "slow-half-a-beat-from-end",
        "fast-more-than-half-a-beat",
    ],
)
def test_split_exactly_half_a_beat_from_an_edge_is_accepted(at_ms, index):
    out = split(_three(), at_ms)

    assert len(out) == 4
    assert out[index].end_ms == out[index + 1].start_ms == at_ms


@pytest.mark.parametrize(
    "at_ms",
    [500.0, 13500.0, 1000.0, 5000.0, 13000.0, 1249.9, 4750.1, 5400.0, 8600.0, 9100.0],
    ids=[
        "before-the-map",
        "after-the-map",
        "on-the-map-start",
        "on-a-boundary",
        "on-the-map-end",
        "just-under-half-a-beat-from-start",
        "just-under-half-a-beat-from-end",
        "slow-under-half-a-beat-from-start",
        "slow-under-half-a-beat-from-end",
        "fast-under-half-a-beat-from-start",
    ],
)
def test_split_outside_a_segment_or_too_close_to_its_edge_is_refused(at_ms):
    with pytest.raises(TempoEditError):
        split(_three(), at_ms)


def _tempo_change(change_beat):
    # 150 bpm up to change_beat, then 200 bpm, the phase carries on across the change
    slow, fast = 60000.0 / 150.0, 60000.0 / 200.0
    change_ms = 1000.0 + slow * change_beat
    times = np.concatenate([1000.0 + slow * np.arange(change_beat), change_ms + fast * np.arange(24)])
    return times, change_ms, fast


@pytest.mark.parametrize(
    "change_beat, beats_to_downbeat",
    [(18, 2), (20, 0)],
    ids=["change-between-downbeats", "change-on-a-downbeat"],
)
def test_split_at_a_tempo_change_refits_both_halves(change_beat, beats_to_downbeat):
    times, change_ms, fast = _tempo_change(change_beat)
    # one auto segment over both tempos, its bpm is a compromise
    parent = _seg(600.0, float(times[-1]) + 300.0, bpm=171.4, anchor=1000.0, confidence=0.6)

    left, right = split([parent], change_ms, _tracked(times))

    assert left.bpm == pytest.approx(150.0, abs=BPM_TOLERANCE)
    assert left.anchor_ms == pytest.approx(1000.0, abs=ANCHOR_TOLERANCE_MS)
    assert right.bpm == pytest.approx(200.0, abs=BPM_TOLERANCE)
    assert right.anchor_ms == pytest.approx(change_ms + fast * beats_to_downbeat, abs=ANCHOR_TOLERANCE_MS)
    assert left.confidence is not None
    assert right.confidence is not None
    assert left.source == right.source == "manual"
    assert (left.start_ms, left.end_ms, right.start_ms, right.end_ms) == (600.0, change_ms, change_ms, parent.end_ms)


@pytest.mark.parametrize(
    "left_beats, left_refit, right_refit",
    [
        (MIN_BEATS - 1, False, True),
        (MIN_BEATS, True, True),
        (STEADY_BEATS - MIN_BEATS, True, True),
        (STEADY_BEATS - MIN_BEATS + 1, True, False),
    ],
    ids=["left-one-beat-short", "left-exactly-min-beats", "right-exactly-min-beats", "right-one-beat-short"],
)
def test_split_refits_only_the_halves_with_enough_beats(left_beats, left_refit, right_refit):
    # the parent says 120 bpm and the beats say 125, so a refit shows in the bpm
    parent = _seg(0.0, 19000.0, bpm=120.0, anchor=100.0, confidence=0.9)
    # the beat at the split time belongs to the right half
    at_ms = STEADY_PERIOD_MS * left_beats

    left, right = split([parent], at_ms, _tracked(STEADY_PERIOD_MS * np.arange(STEADY_BEATS)))

    if left_refit:
        assert left.bpm == pytest.approx(125.0, abs=BPM_TOLERANCE)
        assert left.anchor_ms == pytest.approx(0.0, abs=ANCHOR_TOLERANCE_MS)
        assert left.confidence is not None
    else:
        assert (left.bpm, left.anchor_ms, left.confidence) == (120.0, 100.0, None)
    if right_refit:
        first_downbeat_ms = STEADY_PERIOD_MS * 4 * math.ceil(left_beats / 4)
        assert right.bpm == pytest.approx(125.0, abs=BPM_TOLERANCE)
        assert right.anchor_ms == pytest.approx(first_downbeat_ms, abs=ANCHOR_TOLERANCE_MS)
        assert right.confidence is not None
    else:
        first_line_ms = 100.0 + 500.0 * math.ceil((at_ms - 100.0) / 500.0)
        assert (right.bpm, right.anchor_ms, right.confidence) == (120.0, first_line_ms, None)


def test_split_counts_a_beat_just_before_the_boundary_in_the_right_half():
    parent = _seg(0.0, 19000.0, bpm=120.0, anchor=100.0, confidence=0.9)
    times = STEADY_PERIOD_MS * np.arange(STEADY_BEATS)
    first_right = STEADY_BEATS - MIN_BEATS
    at_ms = times[first_right]
    # the tracker put the first beat of the right half a little early, which would leave the right half one beat short
    times[first_right] -= 10.0

    _, right = split([parent], at_ms, _tracked(times))

    assert right.confidence is not None


@pytest.mark.parametrize(
    "confidence, with_tracked",
    [(None, True), (0.9, False)],
    ids=["hand-set-parent", "no-tracked-beats"],
)
@pytest.mark.parametrize(
    "at_ms, right_anchor_ms",
    [(3600.0, 3600.0), (3601.0, 4100.0), (4090.0, 4100.0)],
    ids=["on-a-grid-line", "just-after-a-grid-line", "just-before-a-grid-line"],
)
def test_split_keeps_the_grid_when_there_is_nothing_to_refit_from(confidence, with_tracked, at_ms, right_anchor_ms):
    parent = _seg(0.0, 19000.0, bpm=120.0, anchor=100.0, confidence=confidence)
    # beats at another tempo are there for the hand-set case, a refit would pick them up
    tracked = _tracked(STEADY_PERIOD_MS * np.arange(STEADY_BEATS)) if with_tracked else None

    left, right = split([parent], at_ms, tracked)

    assert (left.bpm, left.anchor_ms, left.confidence) == (120.0, 100.0, None)
    assert (right.bpm, right.anchor_ms, right.confidence) == (120.0, right_anchor_ms, None)
    assert left.source == right.source == "manual"
    # every grid line of the right half is where it was before
    lines_from_parent_anchor = (right.anchor_ms - parent.anchor_ms) / 500.0
    assert lines_from_parent_anchor == pytest.approx(round(lines_from_parent_anchor))


# --- merge ---


def test_merge_of_a_false_split_goes_back_to_the_true_tempo():
    # 128 bpm all the way, split in two halves that each got a slightly wrong tempo
    times = 500.0 + 60000.0 / 128.0 * np.arange(64)
    first = _seg(400.0, 15000.0, bpm=127.2, anchor=500.0, confidence=0.9, source="manual")
    second = _seg(15000.0, 30200.0, bpm=128.9, anchor=15500.0, confidence=0.8, source="manual")

    out = merge([first, second], 0, _tracked(times))

    assert len(out) == 1
    assert out[0].bpm == pytest.approx(128.0, abs=BPM_TOLERANCE)
    assert out[0].anchor_ms == pytest.approx(500.0, abs=ANCHOR_TOLERANCE_MS)
    assert out[0].confidence is not None
    assert out[0].source == "manual"
    assert (out[0].start_ms, out[0].end_ms) == (400.0, 30200.0)


@pytest.mark.parametrize(
    "first_confidence, second_confidence, winner",
    [(None, 0.9, 0), (0.9, None, 1), (None, None, 0)],
    ids=["first-hand-set", "second-hand-set", "both-hand-set"],
)
def test_merge_with_a_hand_set_segment_keeps_its_grid(first_confidence, second_confidence, winner):
    segments = [
        _seg(500.0, 1000.0),
        _seg(1000.0, 5000.0, bpm=100.0, anchor=1010.0, confidence=first_confidence),
        _seg(5000.0, 9000.0, bpm=140.0, anchor=5020.0, confidence=second_confidence),
        _seg(9000.0, 13000.0),
    ]
    # steady beats across both, a refit would land on 125
    tracked = _tracked(1000.0 + STEADY_PERIOD_MS * np.arange(24))

    out = merge(segments, 1, tracked)

    assert len(out) == 3
    assert out[0] == segments[0]
    assert out[2] == segments[3]
    assert (out[1].bpm, out[1].anchor_ms) == (segments[1 + winner].bpm, segments[1 + winner].anchor_ms)
    assert out[1].confidence is None
    assert out[1].source == "manual"
    assert (out[1].start_ms, out[1].end_ms) == (1000.0, 9000.0)
    _assert_valid_map(out)


@pytest.mark.parametrize("count", [1, 3], ids=["only-segment", "three-segments"])
def test_merging_the_last_segment_is_refused(count):
    with pytest.raises(TempoEditError):
        merge(_three()[:count], count - 1)


# --- keep_manual_segments ---


@pytest.mark.parametrize(
    "previous",
    [[], [_seg(1000.0, 12000.0, bpm=77.0)]],
    ids=["nothing-before", "only-auto-before"],
)
def test_without_manual_segments_the_fresh_map_comes_back_unchanged(previous):
    fresh = _fresh()

    assert keep_manual_segments(previous, fresh) == fresh


@pytest.mark.parametrize(
    "previous, expected",
    [
        pytest.param(
            [_hand(5500.0, 9500.0, 81.0)],
            [(1000.0, 4000.0, 100.0), (4000.0, 5500.0, 110.0), (5500.0, 9500.0, 81.0), (9500.0, 12000.0, 140.0)],
            id="middle-across-two-boundaries",
        ),
        pytest.param(
            [_hand(5000.0, 7000.0, 82.0)],
            [(1000.0, 4000.0, 100.0), (4000.0, 5000.0, 110.0), (5000.0, 7000.0, 82.0), (7000.0, 8000.0, 110.0), (8000.0, 12000.0, 140.0)],
            id="middle-inside-one-fresh-segment",
        ),
        pytest.param(
            [_hand(1000.0, 5000.0, 81.0), _hand(10000.0, 12000.0, 82.0)],
            [(1000.0, 5000.0, 81.0), (5000.0, 8000.0, 110.0), (8000.0, 10000.0, 140.0), (10000.0, 12000.0, 82.0)],
            id="first-and-last",
        ),
        pytest.param(
            [_hand(3000.0, 6000.0, 81.0), _hand(6000.0, 9000.0, 82.0)],
            [(1000.0, 3000.0, 100.0), (3000.0, 6000.0, 81.0), (6000.0, 9000.0, 82.0), (9000.0, 12000.0, 140.0)],
            id="two-adjacent",
        ),
        pytest.param(
            [_hand(10000.0, 14000.0, 81.0, confidence=0.8)],
            [(1000.0, 4000.0, 100.0), (4000.0, 8000.0, 110.0), (8000.0, 10000.0, 140.0), (10000.0, 14000.0, 81.0)],
            id="reaches-past-the-fresh-end",
        ),
        pytest.param(
            [_hand(500.0, 13000.0, 81.0)],
            [(500.0, 13000.0, 81.0)],
            id="covers-the-whole-fresh-map",
        ),
        pytest.param(
            [_hand(200.0, 600.0, 81.0)],
            [(200.0, 600.0, 81.0), (600.0, 4000.0, 100.0), (4000.0, 8000.0, 110.0), (8000.0, 12000.0, 140.0)],
            id="before-the-fresh-map-stretches-first-back",
        ),
        pytest.param(
            [_hand(12500.0, 13000.0, 81.0)],
            [(1000.0, 4000.0, 100.0), (4000.0, 8000.0, 110.0), (8000.0, 12500.0, 140.0), (12500.0, 13000.0, 81.0)],
            id="after-the-fresh-map-stretches-last-forward",
        ),
        pytest.param(
            [_hand(200.0, 600.0, 81.0), _hand(800.0, 900.0, 82.0)],
            [
                (200.0, 600.0, 81.0),
                (600.0, 800.0, 100.0),
                (800.0, 900.0, 82.0),
                (900.0, 4000.0, 100.0),
                (4000.0, 8000.0, 110.0),
                (8000.0, 12000.0, 140.0),
            ],
            id="gap-between-manuals-before-the-fresh-map",
        ),
        pytest.param(
            [_hand(12500.0, 13000.0, 81.0), _hand(13500.0, 14000.0, 82.0)],
            [
                (1000.0, 4000.0, 100.0),
                (4000.0, 8000.0, 110.0),
                (8000.0, 12500.0, 140.0),
                (12500.0, 13000.0, 81.0),
                (13000.0, 13500.0, 140.0),
                (13500.0, 14000.0, 82.0),
            ],
            id="gap-between-manuals-after-the-fresh-map",
        ),
    ],
)
def test_manual_segments_stay_and_fresh_segments_fill_the_gaps(previous, expected):
    fresh = _fresh()

    out = keep_manual_segments(previous, fresh)

    assert [(s.start_ms, s.end_ms, s.bpm) for s in out] == expected
    # manual segments come back untouched, byte for byte
    assert [s for s in out if s.source == "manual"] == previous
    # clipping moves edges only, a fresh segment keeps its own grid
    origin = {s.bpm: s for s in fresh}
    autos = [s for s in out if s.source == "auto"]
    assert [(s.anchor_ms, s.confidence) for s in autos] == [(origin[s.bpm].anchor_ms, origin[s.bpm].confidence) for s in autos]
    _assert_valid_map(out)


def test_auto_segments_from_before_are_dropped():
    previous = [_seg(1000.0, 5000.0, bpm=77.0), _hand(5000.0, 8000.0, 81.0), _seg(8000.0, 12000.0, bpm=88.0)]
    fresh = [_seg(1000.0, 12000.0, bpm=120.0)]

    out = keep_manual_segments(previous, fresh)

    assert [(s.start_ms, s.end_ms, s.bpm) for s in out] == [(1000.0, 5000.0, 120.0), (5000.0, 8000.0, 81.0), (8000.0, 12000.0, 120.0)]
    assert {77.0, 88.0}.isdisjoint(s.bpm for s in out)
    _assert_valid_map(out)


def test_keep_manual_segments_leaves_both_inputs_alone():
    previous = [_seg(1000.0, 5000.0, bpm=77.0), _hand(5000.0, 9000.0, 81.0)]
    fresh = _fresh()
    previous_before = [s.model_copy() for s in previous]
    fresh_before = [s.model_copy() for s in fresh]

    out = keep_manual_segments(previous, fresh)

    assert out is not fresh
    assert previous == previous_before
    assert fresh == fresh_before
