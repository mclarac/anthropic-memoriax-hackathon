import { describe, expect, it } from "vitest";
import type { WorkerRequest, WorkerResponse } from "./protocol";
import { Transcriber, type WorkerLike } from "./transcriber";

class FakeWorker implements WorkerLike {
  sent: WorkerRequest[] = [];
  onmessage: ((event: MessageEvent<WorkerResponse>) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  terminated = false;

  postMessage(message: WorkerRequest) {
    this.sent.push(message);
  }
  terminate() {
    this.terminated = true;
  }
  emit(data: WorkerResponse) {
    this.onmessage?.({ data } as MessageEvent<WorkerResponse>);
  }
}

describe("Transcriber", () => {
  it("asks the worker to load once and resolves when it reports ready", async () => {
    const worker = new FakeWorker();
    const transcriber = new Transcriber(() => worker);
    const first = transcriber.load(() => {});
    const second = transcriber.load(() => {});
    expect(worker.sent).toEqual([{ type: "load" }]);
    worker.emit({ type: "ready" });
    await Promise.all([first, second]);
  });

  it("reports overall download progress across files", async () => {
    const worker = new FakeWorker();
    const transcriber = new Transcriber(() => worker);
    const seen: number[] = [];
    const loading = transcriber.load((fraction) => seen.push(fraction));
    worker.emit({ type: "progress", file: "encoder.onnx", loaded: 50, total: 100 });
    worker.emit({ type: "progress", file: "decoder.onnx", loaded: 0, total: 100 });
    worker.emit({ type: "progress", file: "decoder.onnx", loaded: 100, total: 100 });
    worker.emit({ type: "ready" });
    await loading;
    expect(seen).toEqual([0.5, 0.25, 0.75]);
  });

  it("rejects loading when the worker fails, and allows a retry", async () => {
    const workers: FakeWorker[] = [];
    const transcriber = new Transcriber(() => {
      const w = new FakeWorker();
      workers.push(w);
      return w;
    });
    const failing = transcriber.load(() => {});
    workers[0].emit({ type: "error", message: "WebGPU adapter lost" });
    await expect(failing).rejects.toThrow("WebGPU adapter lost");
    expect(workers[0].terminated).toBe(true);

    const retry = transcriber.load(() => {});
    expect(workers).toHaveLength(2);
    workers[1].emit({ type: "ready" });
    await retry;
  });

  it("sends audio with a request id and resolves with the matching transcript", async () => {
    const worker = new FakeWorker();
    const transcriber = new Transcriber(() => worker);
    const loading = transcriber.load(() => {});
    worker.emit({ type: "ready" });
    await loading;

    const audio = Float32Array.of(0.1, 0.2);
    const a = transcriber.transcribe(audio);
    const b = transcriber.transcribe(Float32Array.of(0.3));
    const [reqA, reqB] = worker.sent.slice(1) as Extract<WorkerRequest, { type: "transcribe" }>[];
    expect(reqA.audio).toEqual(audio);
    expect(reqA.id).not.toBe(reqB.id);

    worker.emit({ type: "result", id: reqB.id, text: " second " });
    worker.emit({ type: "result", id: reqA.id, text: " first " });
    expect(await a).toBe("first");
    expect(await b).toBe("second");
  });

  it("rejects a transcription the worker reports as failed", async () => {
    const worker = new FakeWorker();
    const transcriber = new Transcriber(() => worker);
    const loading = transcriber.load(() => {});
    worker.emit({ type: "ready" });
    await loading;
    const pending = transcriber.transcribe(Float32Array.of(0));
    const { id } = worker.sent[1] as Extract<WorkerRequest, { type: "transcribe" }>;
    worker.emit({ type: "error", id, message: "out of memory" });
    await expect(pending).rejects.toThrow("out of memory");
  });

  it("refuses to transcribe before the model is loaded", async () => {
    const transcriber = new Transcriber(() => new FakeWorker());
    await expect(transcriber.transcribe(Float32Array.of(0))).rejects.toThrow(/not loaded/i);
  });

  it("rejects pending work when the worker crashes", async () => {
    const worker = new FakeWorker();
    const transcriber = new Transcriber(() => worker);
    const loading = transcriber.load(() => {});
    worker.onerror?.({ message: "worker script failed" } as ErrorEvent);
    await expect(loading).rejects.toThrow("worker script failed");
  });
});
