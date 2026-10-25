import { type ReactNode, useRef } from "react";
import { AUDIO_EXTENSIONS } from "../fileDrop";
import { formatBytes } from "../format";

export interface UploadProgress {
  fraction: number;
  complete: boolean;
}

interface Props {
  // a picked file that hasn't been analyzed yet, the analyze button is for it
  file: File | null;
  // a song is open on the page, so the button picks another one
  songOpen: boolean;
  // the big drop zone before a song is open, a small block in the source column after
  variant: "start" | "compact";
  // a dropped file that wasn't audio, and the like
  notice: string | null;
  onChoose: (file: File) => void;
  onAnalyze: () => void;
  // the start screen offers the generated demo track
  onDemo?: () => void;
  // the reopen prompt and the last run's stage track, under the button
  children?: ReactNode;
}

const ACCEPT = AUDIO_EXTENSIONS.join(",");

// only shown while nothing runs, an analysis in progress has its own block instead of this one
export function UploadPanel({ file, songOpen, variant, notice, onChoose, onAnalyze, onDemo, children }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const start = variant === "start";

  return (
    <div className={start ? "upload upload--start" : "upload"}>
      {start && <p className="upload__title">drop a song anywhere on the page</p>}
      <div className="picker">
        <div className="picker__row">
          <button
            type="button"
            className={`btn ${start && file === null ? "btn--primary btn--big" : "btn--outline"}`}
            data-tour={start ? "upload" : undefined}
            title="pick an mp3, wav, flac, ogg or m4a file, or drop one anywhere on the page"
            onClick={() => inputRef.current?.click()}
          >
            {songOpen ? "choose another song" : "choose a song"}
          </button>
          <span className="picker__hint mono">mp3 · wav · flac · ogg · m4a</span>
        </div>
        {file !== null && (
          <p className="picker__file mono">
            <span className="picker__name">{file.name}</span>
            <span className="picker__size">{formatBytes(file.size)}</span>
          </p>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          hidden
          onChange={(event) => {
            const chosen = event.target.files?.[0];
            // same file twice in a row wouldn't fire change without this
            event.target.value = "";
            if (chosen) onChoose(chosen);
          }}
        />
      </div>
      {notice !== null && <p className="upload__notice">{notice}</p>}

      {file !== null && (
        <button
          type="button"
          className={`btn btn--primary${start ? " btn--big" : ""}`}
          title="upload the song and run the analysis, a file analyzed before offers its earlier job first"
          onClick={onAnalyze}
        >
          analyze
        </button>
      )}

      {children}
      {start && file === null && (
        <>
          <ol className="upload__steps">
            <li>choose or drop a song</li>
            <li>analyze, about a minute for a 4 minute song</li>
            <li>type the offset, bpm and time signature into the chart editor</li>
          </ol>
          {onDemo !== undefined && (
            <p className="upload__demo">
              <button
                type="button"
                className="btn btn--outline"
                title="analyze a 30 s click track with drums made on this machine, no real music, and show the tour on it"
                onClick={onDemo}
              >
                try with a demo
              </button>
              <span className="upload__demo-note">a generated click track, it stays out of the recent list</span>
            </p>
          )}
        </>
      )}
      {start && <p className="upload__local">runs on this machine, the song is kept in the local data/ folder</p>}
    </div>
  );
}
