import type { WorkerRequest, WorkerResponse } from "./protocol";

export interface WorkerLike {
  postMessage(message: WorkerRequest, transfer?: Transferable[]): void;
  terminate(): void;
  onmessage: ((event: MessageEvent<WorkerResponse>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
}

interface Settler<T> {
  resolve: (value: T) => void;
  reject: (error: Error) => void;
}

/** Main-thread handle for the Whisper worker: one model load, many transcriptions. */
export class Transcriber {
  private worker: WorkerLike | null = null;
  private loading: Promise<void> | null = null;
  private loaded = false;
  private loadSettler: Settler<void> | null = null;
  private onProgress: (fraction: number) => void = () => {};
  private readonly files = new Map<string, { loaded: number; total: number }>();
  private readonly pending = new Map<number, Settler<string>>();
  private nextId = 1;

  constructor(private readonly createWorker: () => WorkerLike) {}

  load(onProgress: (fraction: number) => void): Promise<void> {
    this.onProgress = onProgress;
    if (this.loading) return this.loading;
    const worker = this.createWorker();
    this.worker = worker;
    worker.onmessage = (event) => this.handle(event.data);
    worker.onerror = (event) => this.fail(new Error(event.message));
    this.loading = new Promise<void>((resolve, reject) => {
      this.loadSettler = { resolve, reject };
    });
    worker.postMessage({ type: "load" });
    return this.loading;
  }

  transcribe(audio: Float32Array): Promise<string> {
    if (!this.loaded || !this.worker) return Promise.reject(new Error("Speech model is not loaded yet"));
    const id = this.nextId++;
    const result = new Promise<string>((resolve, reject) => this.pending.set(id, { resolve, reject }));
    this.worker.postMessage({ type: "transcribe", id, audio }, [audio.buffer]);
    return result;
  }

  private handle(message: WorkerResponse): void {
    switch (message.type) {
      case "progress": {
        this.files.set(message.file, { loaded: message.loaded, total: message.total });
        let loaded = 0;
        let total = 0;
        for (const file of this.files.values()) {
          loaded += file.loaded;
          total += file.total;
        }
        if (total > 0) this.onProgress(loaded / total);
        return;
      }
      case "ready":
        this.loaded = true;
        this.loadSettler?.resolve();
        this.loadSettler = null;
        return;
      case "result":
        this.pending.get(message.id)?.resolve(message.text.trim());
        this.pending.delete(message.id);
        return;
      case "error":
        if (message.id !== undefined) {
          this.pending.get(message.id)?.reject(new Error(message.message));
          this.pending.delete(message.id);
        } else {
          this.fail(new Error(message.message));
        }
    }
  }

  private fail(error: Error): void {
    this.worker?.terminate();
    this.worker = null;
    this.loading = null;
    this.loaded = false;
    this.files.clear();
    this.loadSettler?.reject(error);
    this.loadSettler = null;
    for (const settler of this.pending.values()) settler.reject(error);
    this.pending.clear();
  }
}
