import { prepareWhisperInput } from "../audio/resample";

export class MicrophoneError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MicrophoneError";
  }
}

/** Records the microphone as raw PCM while push-to-talk is held. Nothing is uploaded. */
export class MicRecorder {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private chunks: Float32Array[][] = [];

  get recording(): boolean {
    return this.node !== null;
  }

  async start(): Promise<void> {
    if (this.recording) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
    } catch (error) {
      const denied = error instanceof DOMException && error.name === "NotAllowedError";
      throw new MicrophoneError(
        denied ? "Microphone access was blocked. Allow it in the browser, or type instead." : "No microphone could be opened.",
      );
    }
    this.chunks = [];
    this.context = new AudioContext();
    await this.context.audioWorklet.addModule("/pcm-capture.worklet.js");
    this.source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, "pcm-capture");
    this.node.port.onmessage = (event: MessageEvent<Float32Array[]>) => this.chunks.push(event.data);
    this.source.connect(this.node);
  }

  /** Stops capture and returns 16 kHz mono audio, empty when nothing was heard. */
  async stop(): Promise<Float32Array> {
    const context = this.context;
    if (!context) return new Float32Array(0);
    const rate = context.sampleRate;
    this.source?.disconnect();
    this.node?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.source = null;
    this.node = null;
    this.stream = null;
    this.context = null;
    await context.close();
    const chunks = this.chunks;
    this.chunks = [];
    return prepareWhisperInput(chunks, rate);
  }
}

export function hasWebGpu(): boolean {
  return typeof navigator !== "undefined" && "gpu" in navigator && Boolean(navigator.gpu);
}
