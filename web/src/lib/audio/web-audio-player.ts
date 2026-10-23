import type { ClipPlayer } from "./playback-queue";

/** Plays decoded WAV clips one at a time through a single AudioContext. */
export class WebAudioPlayer implements ClipPlayer<AudioBuffer> {
  private context: AudioContext | null = null;
  private current: AudioBufferSourceNode | null = null;

  private ensureContext(): AudioContext {
    this.context ??= new AudioContext();
    return this.context;
  }

  /** Browsers keep a new context suspended until the page has seen a user gesture. */
  async unlock(): Promise<void> {
    const context = this.ensureContext();
    if (context.state === "suspended") await context.resume();
  }

  decode(wav: ArrayBuffer): Promise<AudioBuffer> {
    return this.ensureContext().decodeAudioData(wav);
  }

  async play(clip: AudioBuffer): Promise<void> {
    const context = this.ensureContext();
    if (context.state === "suspended") await context.resume();
    await new Promise<void>((resolve) => {
      const source = context.createBufferSource();
      source.buffer = clip;
      source.connect(context.destination);
      source.onended = () => {
        if (this.current === source) this.current = null;
        resolve();
      };
      this.current = source;
      source.start();
    });
  }

  stop(): void {
    this.current?.stop();
  }
}
