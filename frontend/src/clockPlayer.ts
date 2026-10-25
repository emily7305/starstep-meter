// plays the decoded wav through an AudioContext the app owns, so the click track can be
// scheduled on the exact clock the music plays on. wavesurfer takes it as its media element,
// it only uses the parts of HTMLMediaElement below.
//
// the music isn't started "now". start(when) with a time that's already gone starts whenever the
// audio thread gets to it, a few ms after the time the code read, and clicks timed off that read
// would come out early by as much. so it's started a little ahead on the context clock like the
// clicks are, and contextTimeAt() is exact for both

type Listener = () => void;

// long enough that start() lands before the time it names, short enough not to feel laggy
export const START_LEAD_S = 0.05;

// the slice of AudioContext this needs, so the tests can hand in a fake
export interface ClockContext {
  readonly currentTime: number;
  readonly state: AudioContextState;
  readonly destination: AudioNode;
  createGain(): GainNode;
  createBufferSource(): AudioBufferSourceNode;
  decodeAudioData(data: ArrayBuffer): Promise<AudioBuffer>;
  resume(): Promise<void>;
  close(): Promise<void>;
}

export class ClockPlayer {
  readonly context: ClockContext;
  private readonly gain: GainNode;
  private readonly listeners = new Map<string, Set<Listener>>();
  private buffer: AudioBuffer | null = null;
  private source: AudioBufferSourceNode | null = null;
  // while playing, songStart (s) plays at contextStart on the context clock
  private songStart = 0;
  private contextStart = 0;
  // while paused, where playback picks up again
  private position = 0;
  private rate = 1;
  private volumeLevel = 1;
  private isMuted = false;
  private loading = 0;
  // goes up whenever the song-to-context mapping changes, the click track reschedules on it
  epoch = 0;
  currentSrc = "";
  paused = true;
  ended = false;
  seeking = false;
  autoplay = false;
  controls = false;
  preservesPitch = true;
  error: Error | null = null;

  constructor(context: ClockContext = new AudioContext()) {
    this.context = context;
    this.gain = context.createGain();
    this.gain.connect(context.destination);
  }

  addEventListener(event: string, listener: Listener, options?: { once?: boolean }): void {
    const wrapped = options?.once
      ? () => {
          this.removeEventListener(event, wrapped);
          listener();
        }
      : listener;
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)?.add(wrapped);
  }

  removeEventListener(event: string, listener: Listener): void {
    this.listeners.get(event)?.delete(listener);
  }

  private emit(...events: string[]): void {
    for (const event of events) for (const listener of [...(this.listeners.get(event) ?? [])]) listener();
  }

  get src(): string {
    return this.currentSrc;
  }

  set src(value: string) {
    const wasPlaying = !this.paused;
    this.stopSource();
    this.currentSrc = value;
    this.buffer = null;
    this.position = 0;
    this.paused = true;
    this.error = null;
    const id = ++this.loading;
    if (wasPlaying) this.emit("pause");
    if (!value) {
      this.emit("emptied");
      return;
    }
    fetch(value)
      .then((res) => {
        if (!res.ok) throw new Error(`could not fetch the audio, http ${res.status}`);
        return res.arrayBuffer();
      })
      .then((data) => this.context.decodeAudioData(data))
      .then((buffer) => {
        // a newer src took over while this one was decoding
        if (id !== this.loading) return;
        this.buffer = buffer;
        this.emit("loadedmetadata", "durationchange", "canplay");
      })
      .catch((err: unknown) => {
        if (id !== this.loading) return;
        this.error = err instanceof Error ? err : new Error("could not decode the audio");
        this.emit("error");
      });
  }

  get duration(): number {
    return this.buffer?.duration ?? 0;
  }

  get currentTime(): number {
    if (this.paused) return this.position;
    // inside the start lead the music hasn't started, so the playhead waits with it
    const t = this.songStart + Math.max(0, this.context.currentTime - this.contextStart) * this.rate;
    return Math.min(t, this.duration);
  }

  set currentTime(value: number) {
    const playing = !this.paused;
    if (playing) this.stopSource();
    this.position = Math.max(0, Math.min(value, this.duration));
    this.ended = false;
    if (playing) this.startSource();
    this.emit("seeking", "timeupdate", "seeked");
  }

  get playbackRate(): number {
    return this.rate;
  }

  set playbackRate(value: number) {
    if (!(value > 0) || value === this.rate) return;
    const playing = !this.paused;
    if (playing) {
      this.position = this.currentTime;
      this.stopSource();
    }
    this.rate = value;
    if (playing) this.startSource();
    this.emit("ratechange");
  }

  get volume(): number {
    return this.volumeLevel;
  }

  set volume(value: number) {
    this.volumeLevel = value;
    this.gain.gain.value = this.isMuted ? 0 : value;
    this.emit("volumechange");
  }

  get muted(): boolean {
    return this.isMuted;
  }

  set muted(value: boolean) {
    this.isMuted = value;
    this.gain.gain.value = value ? 0 : this.volumeLevel;
    this.emit("volumechange");
  }

  async play(): Promise<void> {
    if (!this.paused || this.buffer === null) return;
    // a context made before any click starts suspended, play() always comes from a click
    if (this.context.state === "suspended") await this.context.resume();
    if (!this.paused) return;
    if (this.position >= this.duration) this.position = 0;
    this.paused = false;
    this.ended = false;
    this.startSource();
    this.emit("play");
  }

  pause(): void {
    if (this.paused) return;
    this.position = this.currentTime;
    this.stopSource();
    this.paused = true;
    this.emit("pause");
  }

  // the context time a song position (s) plays at, null while paused
  contextTimeAt(songSeconds: number): number | null {
    if (this.paused) return null;
    return this.contextStart + (songSeconds - this.songStart) / this.rate;
  }

  canPlayType(type: string): string {
    return /^audio\//.test(type) ? "maybe" : "";
  }

  load(): void {
    // nothing to reset, setting src does it all
  }

  removeAttribute(name: string): void {
    if (name === "src") this.src = "";
  }

  async setSinkId(id: string): Promise<void> {
    const ctx = this.context as ClockContext & { setSinkId?: (id: string) => Promise<void> };
    await ctx.setSinkId?.(id);
  }

  remove(): void {
    this.destroy();
  }

  destroy(): void {
    this.stopSource();
    this.loading += 1;
    this.listeners.clear();
    this.gain.disconnect();
    void this.context.close().catch(() => undefined);
  }

  private startSource(): void {
    if (this.buffer === null) return;
    const node = this.context.createBufferSource();
    node.buffer = this.buffer;
    node.playbackRate.value = this.rate;
    node.connect(this.gain);
    this.contextStart = this.context.currentTime + START_LEAD_S;
    this.songStart = this.position;
    node.start(this.contextStart, this.position);
    node.onended = () => {
      if (node !== this.source) return;
      this.source = null;
      this.position = this.duration;
      this.paused = true;
      this.ended = true;
      this.epoch += 1;
      this.emit("timeupdate", "pause", "ended");
    };
    this.source = node;
    this.epoch += 1;
  }

  private stopSource(): void {
    const node = this.source;
    if (node === null) return;
    this.source = null;
    node.onended = null;
    try {
      node.stop();
    } catch {
      // already stopped
    }
    node.disconnect();
    this.epoch += 1;
  }
}
