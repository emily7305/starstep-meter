import type { HealthStatus } from "../types/api";

export type Health =
  | { kind: "loading" }
  | { kind: "offline" }
  | { kind: "ok"; status: HealthStatus };

interface Props {
  health: Health;
}

interface Item {
  name: string;
  ok: boolean;
  required: boolean;
  // what it reads when it isn't ok
  off: string;
  title?: string;
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

  // madmom is optional, librosa tracks beats without it, so it being off is a note and not an error
  const { status } = health;
  const items: Item[] = [
    { name: "ffmpeg", ok: status.ffmpeg, required: true, off: "missing" },
    { name: "ffprobe", ok: status.ffprobe, required: true, off: "missing" },
    {
      name: "madmom",
      ok: status.madmom,
      required: false,
      // installed but it doesn't import is told apart from not installed, the error is in the tooltip
      off: status.madmom_error ? "failed to import" : "not installed",
      title: status.madmom_error ?? undefined,
    },
  ];

  return (
    <p className="health" aria-live="polite">
      {items.map(({ name, ok, required, off, title }, i) => (
        <span key={name}>
          {i > 0 && <span className="health__sep"> · </span>}
          <span className={ok ? undefined : required ? "health__bad" : "health__off"} title={title}>
            {name} {ok ? "ok" : off}
          </span>
        </span>
      ))}
    </p>
  );
}
