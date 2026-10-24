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

  const items: Array<[string, boolean]> = [
    ["ffmpeg", health.status.ffmpeg],
    ["ffprobe", health.status.ffprobe],
    ["madmom", health.status.madmom],
  ];

  return (
    <p className="health" aria-live="polite">
      {items.map(([name, ok], i) => (
        <span key={name}>
          {i > 0 && <span className="health__sep"> · </span>}
          <span className={ok ? undefined : "health__bad"}>
            {name} {ok ? "ok" : "missing"}
          </span>
        </span>
      ))}
    </p>
  );
}
