"""Sonolus preset values from hand-built tempo and meter maps, every expected number worked out by hand."""

from __future__ import annotations

import gzip
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.analysis.export import sonolus_export
from backend.analysis.sonolus import (
    BpmChange,
    SonolusError,
    TimeSignature,
    decoder_padding_ms,
    level_entities,
    sonolus_timing,
)
from backend.schema.models import AudioSource, MeterSegment, TempoSegment, TimingReport, Trim

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
# 1105 samples at 44.1 kHz, the lame mp3 padding from the decoder padding tests
MP3_PADDING_MS = 25.057


def seg(start: float, end: float, bpm: float, anchor: float) -> TempoSegment:
    return TempoSegment(start_ms=start, end_ms=end, bpm=bpm, anchor_ms=anchor, confidence=1.0, source="auto")


def meter(start: float, end: float, numerator: int, denominator: int = 4) -> MeterSegment:
    return MeterSegment(start_ms=start, end_ms=end, numerator=numerator, denominator=denominator, source="auto")


def report(tempo: list[TempoSegment], meters: list[MeterSegment] | None = None, padding: int = 0) -> TimingReport:
    return TimingReport(
        source=AudioSource(
            filename="click.mp3",
            sha256="ab" * 32,
            duration_ms=21000.0,
            sample_rate=44100,
            codec="mp3",
            decoder_padding_samples=padding,
        ),
        trim=Trim(start_ms=tempo[0].start_ms, end_ms=tempo[-1].end_ms),
        tempo_map=tempo,
        meter_map=meters or [],
    )


def test_anchor_on_a_bar_from_zero_puts_beat_zero_at_the_start_of_the_audio() -> None:
    timing = sonolus_timing([seg(500, 20500, 120, 2000)])

    assert timing.bgm_offset_s == 0.0
    assert timing.first_downbeat_beat == 4.0
    assert timing.bpm_changes == [BpmChange(beat=0.0, bpm=120, time_ms=0.0)]
    assert timing.time_signatures == [TimeSignature(beat=0.0, numerator=4, denominator=4)]


def test_beat_zero_is_the_last_bar_line_before_the_audio_starts() -> None:
    # 2137.5 is a bar and 137.5 ms after 0, so the bar line before 0 is two bars back, at -1862.5
    timing = sonolus_timing([seg(100, 20500, 120, 2137.5)])

    assert timing.bgm_offset_s == -1.8625
    assert timing.first_downbeat_beat == 8.0
    assert timing.bpm_changes == [BpmChange(beat=0.0, bpm=120, time_ms=-1862.5)]


def test_beat_zero_follows_the_first_meter() -> None:
    # 3/4 at 120 is 1500 ms a bar, 2137.5 - 2 * 1500 = -862.5
    timing = sonolus_timing([seg(100, 20500, 120, 2137.5)], [meter(100, 20500, 3)])

    assert timing.bgm_offset_s == -0.8625
    assert timing.first_downbeat_beat == 6.0
    assert timing.time_signatures == [TimeSignature(beat=0.0, numerator=3, denominator=4)]


@pytest.mark.parametrize(("anchor", "plain", "compensated"), [(2000.0, 0.0, 0.025057), (2137.5, -1.8625, -1.837443)])
def test_decoder_compensation_only_moves_the_bgm_offset(anchor: float, plain: float, compensated: float) -> None:
    tempo = [seg(100, 20500, 120, anchor)]
    without = sonolus_timing(tempo)
    with_padding = sonolus_timing(tempo, decoder_compensation_ms=MP3_PADDING_MS)

    assert (without.bgm_offset_s, with_padding.bgm_offset_s) == (plain, compensated)
    # the player hears everything 25 ms late, so the bgm has to be 25 ms further in at level time 0
    assert with_padding.bpm_changes == without.bpm_changes
    assert with_padding.time_signatures == without.time_signatures
    assert with_padding.first_downbeat_beat == without.first_downbeat_beat


def test_a_tempo_change_on_a_beat_of_the_old_grid_lands_on_a_whole_beat() -> None:
    tempo = [seg(500, 10500, 120, 1000), seg(10500, 20500, 150, 10500)]

    timing = sonolus_timing(tempo)

    assert timing.bgm_offset_s == -1.0
    # 11500 ms of 120 bpm from beat 0 at -1000
    assert timing.bpm_changes == [BpmChange(0.0, 120, -1000.0), BpmChange(23.0, 150, 10500.0)]
    # bars from 1000 every 4 beats, the last 120 bpm bar starts at 9000 and is cut to 3 beats by the change
    assert timing.time_signatures == [TimeSignature(0.0, 4, 4), TimeSignature(20.0, 3, 4), TimeSignature(23.0, 4, 4)]


def test_a_change_between_two_beats_keeps_its_exact_time() -> None:
    # the 150 bpm grid starts 0.2 of a beat after the 120 one would have had a line, at 10600
    tempo = [seg(500, 10600, 120, 1000), seg(10600, 20500, 150, 10600)]

    timing = sonolus_timing(tempo)

    assert timing.bpm_changes[1] == BpmChange(23.2, 150, 10600.0)
    # the cut bar is 3.2 beats, which isn't a whole number of 64ths, the next entry restarts exactly
    assert timing.time_signatures[-1] == TimeSignature(23.2, 4, 4)
    assert [t.beat for t in timing.time_signatures] == [0.0, 20.0, 23.2]


def test_a_meter_split_inside_a_segment_starts_its_bars_there() -> None:
    tempo = [seg(500, 20500, 120, 2000)]

    timing = sonolus_timing(tempo, [meter(500, 8000, 4), meter(8000, 20500, 7, 8)])

    # 8000 ms is beat 16, 7/8 is 3.5 beats a bar
    assert timing.time_signatures == [TimeSignature(0.0, 4, 4), TimeSignature(16.0, 7, 8)]


def test_a_partial_bar_before_a_meter_split_gets_its_own_signature() -> None:
    tempo = [seg(500, 20500, 120, 2000)]

    # 9000 ms is two beats into the bar that started at 8000
    timing = sonolus_timing(tempo, [meter(500, 9000, 4), meter(9000, 20500, 3)])

    assert timing.time_signatures == [TimeSignature(0.0, 4, 4), TimeSignature(16.0, 2, 4), TimeSignature(18.0, 3, 4)]


def test_a_segment_with_no_line_of_its_own_adds_no_change() -> None:
    # the 100 bpm sliver's first line would be 10050, past the next segment's quarter beat edge at 9975
    tempo = [seg(500, 10000, 120, 1000), seg(10000, 10100, 100, 10050), seg(10100, 20500, 120, 10100)]

    timing = sonolus_timing(tempo)

    assert timing.bpm_changes == [BpmChange(0.0, 120, -1000.0), BpmChange(22.2, 120, 10100.0)]


def test_level_entities_are_bpm_changes_in_sonolus_shape() -> None:
    timing = sonolus_timing([seg(500, 10500, 120, 1000), seg(10500, 20500, 150, 10500)])

    assert level_entities(timing) == [
        {"archetype": "#BPM_CHANGE", "data": [{"name": "#BEAT", "value": 0.0}, {"name": "#BPM", "value": 120}]},
        {"archetype": "#BPM_CHANGE", "data": [{"name": "#BEAT", "value": 23.0}, {"name": "#BPM", "value": 150}]},
    ]


def test_padding_preset_is_the_padding_in_ms() -> None:
    assert decoder_padding_ms(1105, 44100) == pytest.approx(25.0567, abs=1e-4)
    assert decoder_padding_ms(1105, 48000) == pytest.approx(23.0208, abs=1e-4)
    assert decoder_padding_ms(0, 44100) == 0.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_compensation_has_to_be_a_number(bad: float) -> None:
    with pytest.raises(SonolusError):
        sonolus_timing([seg(500, 20500, 120, 2000)], decoder_compensation_ms=bad)


@pytest.mark.parametrize(("compensation", "offset"), [(0.0, -1.0), (MP3_PADDING_MS, -0.974943)])
def test_sonolus_export_from_a_known_report(compensation: float, offset: float) -> None:
    doc = sonolus_export(report([seg(500, 10500, 120, 1000), seg(10500, 20500, 150, 10500)], padding=1105), NOW, compensation)

    assert doc == {
        "kind": "sonolus",
        "exported_at": "2026-10-25T12:00:00Z",
        "filename": "click.mp3",
        "sha256": "ab" * 32,
        "decoder_compensation_ms": compensation,
        "first_downbeat_beat": 4.0,
        "level_data": {
            "bgmOffset": offset,
            "entities": [
                {"archetype": "#BPM_CHANGE", "data": [{"name": "#BEAT", "value": 0.0}, {"name": "#BPM", "value": 120.0}]},
                {"archetype": "#BPM_CHANGE", "data": [{"name": "#BEAT", "value": 23.0}, {"name": "#BPM", "value": 150.0}]},
            ],
        },
        "bpm_changes": [
            {"beat": 0.0, "bpm": 120.0, "time_ms": -1000.0},
            {"beat": 23.0, "bpm": 150.0, "time_ms": 10500.0},
        ],
        "time_signatures": [
            {"beat": 0.0, "numerator": 4, "denominator": 4},
            {"beat": 20.0, "numerator": 3, "denominator": 4},
            {"beat": 23.0, "numerator": 4, "denominator": 4},
        ],
    }


# --- the test level script ---


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "make_sonolus_test_level.py"
    spec = importlib.util.spec_from_file_location("make_sonolus_test_level", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_test_level_puts_a_note_on_every_grid_beat_across_a_tempo_change() -> None:
    script = _load_script()
    # the 150 bpm grid starts on beat 23.2, its notes count from there
    doc = sonolus_export(report([seg(500, 10600, 120, 1000), seg(10600, 20500, 150, 10600)]), NOW)

    level = script.test_level_data(doc, 22, "NormalTapNote", {"lane": 0.0, "size": 1.5})

    assert level["bgmOffset"] == -1.0
    assert [e["archetype"] for e in level["entities"][:4]] == ["Initialization", "Stage", "#BPM_CHANGE", "#BPM_CHANGE"]
    notes = level["entities"][4:]
    beats = [n["data"][0]["value"] for n in notes]
    assert beats == [4.0 + k for k in range(20)] + [23.2, 24.2]
    assert notes[0]["data"] == [{"name": "#BEAT", "value": 4.0}, {"name": "lane", "value": 0.0}, {"name": "size", "value": 1.5}]


def test_test_level_script_writes_gzipped_level_data(tmp_path: Path) -> None:
    script = _load_script()
    export_path = tmp_path / "song.sonolus.json"
    export_path.write_text(json.dumps(sonolus_export(report([seg(500, 20500, 120, 2000)]), NOW, MP3_PADDING_MS)), encoding="utf-8")

    assert script.main([str(export_path), str(tmp_path / "level.json.gz"), "--beats", "8"]) == 0

    level = json.loads(gzip.decompress((tmp_path / "level.json.gz").read_bytes()))
    assert level["bgmOffset"] == 0.025057
    assert len(level["entities"]) == 2 + 1 + 8


def test_test_level_script_wants_a_sonolus_export(tmp_path: Path, capsys) -> None:
    script = _load_script()
    export_path = tmp_path / "song.timing.json"
    export_path.write_text(json.dumps({"kind": "timing"}), encoding="utf-8")

    assert script.main([str(export_path), str(tmp_path / "level.json.gz")]) == 1
    assert "export with the sonolus preset" in capsys.readouterr().err
