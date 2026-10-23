/// <reference lib="webworker" />
import { pipeline, type AutomaticSpeechRecognitionPipeline } from "@huggingface/transformers";
import type { WorkerRequest, WorkerResponse } from "./protocol";

const MODEL_ID = "onnx-community/whisper-base.en";

// pipeline() has overloads per task that make its full type too large for tsc to resolve.
const createRecognizer = pipeline as unknown as (
  task: "automatic-speech-recognition",
  model: string,
  options: Record<string, unknown>,
) => Promise<AutomaticSpeechRecognitionPipeline>;

let recognizer: Promise<AutomaticSpeechRecognitionPipeline> | null = null;

function post(message: WorkerResponse): void {
  self.postMessage(message);
}

function loadRecognizer(): Promise<AutomaticSpeechRecognitionPipeline> {
  recognizer ??= createRecognizer("automatic-speech-recognition", MODEL_ID, {
    device: "webgpu",
    // The encoder loses accuracy when quantized on WebGPU, so it stays fp32; the
    // decoder tolerates q4 and keeps the first download small.
    dtype: { encoder_model: "fp32", decoder_model_merged: "q4" },
    progress_callback: (item: { status: string; file: string; loaded: number; total: number }) => {
      if (item.status === "progress") {
        post({ type: "progress", file: item.file, loaded: item.loaded, total: item.total });
      }
    },
  });
  return recognizer;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const request = event.data;
  if (request.type === "load") {
    try {
      await loadRecognizer();
      post({ type: "ready" });
    } catch (error) {
      recognizer = null;
      post({ type: "error", message: messageOf(error) });
    }
    return;
  }
  try {
    const transcribe = await loadRecognizer();
    const output = await transcribe(request.audio);
    const text = Array.isArray(output) ? output.map((o) => o.text).join(" ") : output.text;
    post({ type: "result", id: request.id, text });
  } catch (error) {
    post({ type: "error", id: request.id, message: messageOf(error) });
  }
};
