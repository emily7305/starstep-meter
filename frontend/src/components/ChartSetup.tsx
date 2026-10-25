import { useState } from "react";
import { type ChartSetup as Setup, FIRST_MEASURES, formatBeat, formatOffset, midMeasure, setupText } from "../chartSetup";
import { formatFineMs } from "../format";

interface Props {
  setup: Setup;
  filename: string;
  bpmDecimals: number;
  onBpmDecimals: (decimals: number) => void;
  // the row picked last, its line on the timeline gets the accent
  selected: number | null;
  onSelect: (row: number) => void;
  onFirstMeasure: (measure: number) => void;
}

const MORE_DECIMALS = 4;

// song.mp3 -> song.wav, and a wav source gets a name of its own so ffmpeg doesn't write over it
export function wavName(filename: string): string {
  const dot = filename.lastIndexOf(".");
  const stem = dot > 0 ? filename.slice(0, dot) : filename;
  return filename.toLowerCase().endsWith(".wav") ? `${stem}-ffmpeg.wav` : `${stem}.wav`;
}

export function ffmpegCommand(filename: string): string {
  return `ffmpeg -i "${filename}" "${wavName(filename)}"`;
}

// "copied", or why it failed. clipboard needs a secure context and focus, 127.0.0.1 counts as secure
export async function copyToClipboard(text: string): Promise<string> {
  try {
    await navigator.clipboard.writeText(text);
    return "copied";
  } catch (err) {
    return `copy failed — ${err instanceof Error ? err.message : "clipboard not available"}`;
  }
}


export function ChartSetup({ setup, filename, bpmDecimals, onBpmDecimals, selected, onSelect, onFirstMeasure }: Props) {
  const [copyState, setCopyState] = useState<string | null>(null);
  const [commandState, setCommandState] = useState<string | null>(null);
  const command = ffmpegCommand(filename);
  const padding = setup.paddingMs > 0;

  async function copy() {
    setCopyState(await copyToClipboard(setupText(setup, bpmDecimals)));
  }

  return (
    <section className="setup" id="chart-setup" aria-labelledby="setup-label">
      <div className="setup__head">
        <h3 id="setup-label" className="setup__title">
          chart setup
        </h3>
        <button
          type="button"
          className="btn btn--chip"
          aria-pressed={bpmDecimals > 2}
          onClick={() => onBpmDecimals(bpmDecimals > 2 ? 2 : MORE_DECIMALS)}
        >
          more decimals
        </button>
        <button type="button" className="btn btn--outline" onClick={() => void copy()}>
          copy list
        </button>
        {copyState !== null && <span className="setup__copied">{copyState}</span>}
      </div>

      <ol className="setup__steps">
        <li>
          <p className="setup__step">music offset</p>
          <div className="setup__first" role="group" aria-label="the measure the music starts at">
            <span className="setup__note">music starts at measure</span>
            {FIRST_MEASURES.map((m) => (
              <button
                key={m}
                type="button"
                className="btn btn--chip mono"
                aria-pressed={setup.firstMeasure === m}
                onClick={() => onFirstMeasure(m)}
              >
                {m}
              </button>
            ))}
          </div>
          <dl className="setup__offsets">
            <dt>with the wav from ffmpeg</dt>
            <dd className="mono">{formatOffset(setup.wavOffsetMs)}</dd>
            <dt>with the original {setup.kind}</dt>
            <dd className="mono">{formatOffset(setup.originalOffsetMs)}</dd>
          </dl>
          <p className="setup__note">
            the music starts in measure {setup.firstMeasure}, at <span className="mono">{formatFineMs(setup.firstMeasureMs)}</span>
            {setup.firstMeasure > 0 ? ", and measure 0 is one empty bar of lead-in before it" : ""}. measure 0 starts{" "}
            <span className="mono">{formatFineMs(Math.abs(setup.measureZeroMs))}</span>
            {setup.measureZeroMs >= 0 ? " into the audio file" : " before the audio file starts"}. the tool doesn't cut the audio, trim only
            marks where the music starts, so the offset skips whatever comes before measure 0. in mikumikuworld a positive
            offset starts the song later, so the offset is minus where measure 0 is, and positive when measure 0 starts
            before the file.
          </p>
          <p className="setup__note">
            {padding ? (
              <>
                the original {setup.kind} has <span className="mono">{formatFineMs(setup.paddingMs)}</span> of decoder
                padding. mikumikuworld plays it with an mp3 (checked by ear), so the two offsets differ by exactly that
                padding, worked out before rounding.
              </>
            ) : (
              `the original ${setup.kind} has no decoder padding, both offsets are the same.`
            )}
          </p>
        </li>
        <li>
          <p className="setup__step">audio file</p>
          <p className="setup__note">load a wav converted with ffmpeg:</p>
          <div className="setup__command">
            <code className="setup__command-text mono">{command}</code>
            <button type="button" className="btn btn--chip" onClick={() => void copyToClipboard(command).then(setCommandState)}>
              copy command
            </button>
            {commandState !== null && <span className="setup__copied">{commandState}</span>}
          </div>
          <p className="setup__note">
            {padding ? (
              <>
                ffmpeg skips the {setup.kind}'s decoder padding the same way this tool does. loading the original{" "}
                {setup.kind} puts everything <span className="mono">{formatFineMs(setup.paddingMs)}</span> late if the
                editor's player doesn't skip it, use the second offset then.
              </>
            ) : (
              `this ${setup.kind} has no decoder padding, so the original works the same as the converted wav.`
            )}
          </p>
        </li>
        <li>
          <p className="setup__step">bpm and time signature changes, in order</p>
          <p className="setup__note">measures count from 0, like the bar numbers on the timeline. a row jumps there.</p>
          <ol className="setup__rows" aria-label="bpm and time signature changes">
            {setup.rows.map((row, i) => (
              <li key={`${row.kind}-${row.measure}-${row.beat}-${i}`}>
                <button
                  type="button"
                  className="setup__row mono"
                  aria-current={i === selected ? "true" : undefined}
                  onClick={() => onSelect(i)}
                >
                  <span className="setup__measure">m.{row.measure}</span>
                  <span className="setup__beat">{midMeasure(row) ? formatBeat(row.beat) : ""}</span>
                  <span className="setup__value">
                    {row.kind === "bpm" ? `${row.bpm.toFixed(bpmDecimals)} bpm` : `${row.numerator}/${row.denominator}`}
                  </span>
                  {midMeasure(row) && (
                    <span className="setup__warn" title="not on beat 1, place it at this beat inside the measure">
                      mid-measure
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ol>
        </li>
      </ol>
    </section>
  );
}
