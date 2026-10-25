import { type ReactNode, useRef } from "react";
import { AUDIO_EXTENSIONS } from "../fileDrop";
import { formatBytes } from "../format";

export interface UploadProgress {
  fraction: number;
  complete: boolean;
}

interface Props {
  file: File | null;
  busy: boolean;
  progress: UploadProgress | null;
  // the big drop zone before a song is open, a small block in the source column after
  variant: "start" | "compact";
  // a dropped file that wasn't audio, and the like
  notice: string | null;
  onChoose: (file: File) => void;
  onAnalyze: () => void;
  // the stage track and the reopen prompt, they go under the button
  children?: ReactNode;
}

const ACCEPT = AUDIO_EXTENSIONS.join(",");

export function UploadPanel({ file, busy, progress, variant, notice, onChoose, onAnalyze, children }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const percent = progress === null ? 0 : Math.round(progress.fraction * 100);
  let label = "";
  if (progress !== null) label = progress.complete ? "uploaded" : `uploading ${percent}%`;
  const start = variant === "start";

  const choose = (
    <button
      type="button"
      className={`btn ${start && file === null ? "btn--primary btn--big" : "btn--outline"}`}
      title="pick an mp3, wav, flac, ogg or m4a file, or drop one anywhere on the page"
      onClick={() => inputRef.current?.click()}
    >
      {file === null ? "choose a song" : "choose another song"}
    </button>
  );

  return (
    <div className={start ? "upload upload--start" : "upload"} data-tour={start ? "upload" : undefined}>
      {start && <p className="upload__title">drop a song anywhere on the page</p>}
      <div className="picker">
        <div className="picker__row">
          {choose}
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
          disabled={busy}
          title="upload the song and run the analysis, a file analyzed before offers its earlier job first"
          onClick={onAnalyze}
        >
          analyze
        </button>
      )}

      {progress !== null && (
        <div className="progress">
          <div
            className="progress__track"
            role="progressbar"
            aria-label="upload"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress?.complete ? 100 : percent}
          >
            <div className="progress__fill" style={{ width: `${progress?.complete ? 100 : percent}%` }} />
          </div>
          <span className="progress__label mono">{label}</span>
        </div>
      )}
      {children}
      {start && file === null && (
        <ol className="upload__steps">
          <li>choose or drop a song</li>
          <li>analyze, about a minute for a 4 minute song</li>
          <li>type the offset, bpm and time signature into the chart editor</li>
        </ol>
      )}
      {start && <p className="upload__local">runs on this machine, the song is kept in the local data/ folder</p>}
    </div>
  );
}
