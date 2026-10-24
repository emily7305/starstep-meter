import type { HealthStatus } from "../types/api";

export type Health =
  | { kind: "loading" }
  | { kind: "offline" }
  | { kind: "ok"; status: HealthStatus };

interface Props {
  health: Health;
}

export function HealthReadout({ health }: Props) {
  if (health.kind === "loading") return <p className="health" aria-live="polite" />;

  if (health.kind === "offline") {
    return (
      <p className="health" aria-live="polite">
        <span className="health__bad">backend offline</span>
      </p>
    );
  }

  // madmom isn't used until milestone 2, so it missing is a note, not an error
  const items: Array<[string, boolean, boolean]> = [
    ["ffmpeg", health.status.ffmpeg, true],
    ["ffprobe", health.status.ffprobe, true],
    ["madmom", health.status.madmom, false],
  ];

  return (
    <p className="health" aria-live="polite">
      {items.map(([name, ok, required], i) => (
        <span key={name}>
          {i > 0 && <span className="health__sep"> · </span>}
          <span className={ok ? undefined : required ? "health__bad" : "health__off"}>
            {name} {ok ? "ok" : required ? "missing" : "not installed"}
          </span>
        </span>
      ))}
    </p>
  );
}
