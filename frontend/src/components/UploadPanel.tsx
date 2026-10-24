import { useRef } from "react";
import { formatBytes } from "../format";

export interface UploadProgress {
  fraction: number;
  complete: boolean;
}

interface Props {
  file: File | null;
  busy: boolean;
  progress: UploadProgress | null;
  onChoose: (file: File) => void;
  onAnalyze: () => void;
}

const ACCEPT = ".mp3,.wav,.flac,.ogg,.m4a";

export function UploadPanel({ file, busy, progress, onChoose, onAnalyze }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const percent = progress === null ? 0 : Math.round(progress.fraction * 100);
  let label = "";
  if (progress !== null) label = progress.complete ? "uploaded" : `uploading ${percent}%`;

  return (
    <div className="upload">
      <div className="picker">
        <div className="picker__row">
          <button type="button" className="btn btn--outline" onClick={() => inputRef.current?.click()}>
            choose audio file
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

      <button type="button" className="btn btn--primary" disabled={file === null || busy} onClick={onAnalyze}>
        analyze
      </button>

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
    </div>
  );
}
