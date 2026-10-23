/** Whisper models take 16 kHz mono Float32 PCM. */
export const WHISPER_SAMPLE_RATE = 16000;

export function downmixToMono(channels: readonly Float32Array[]): Float32Array {
  if (channels.length === 0) throw new Error("Need at least one channel to downmix");
  const length = channels[0].length;
  if (channels.some((c) => c.length !== length)) {
    throw new Error("All channels must have the same length");
  }
  const mono = new Float32Array(length);
  for (const channel of channels) {
    for (let i = 0; i < length; i++) mono[i] += channel[i];
  }
  if (channels.length > 1) {
    for (let i = 0; i < length; i++) mono[i] /= channels.length;
  }
  return mono;
}

/**
 * Downsampling averages the source span each output sample covers, which acts as a
 * cheap low-pass and avoids aliasing speech into the band Whisper listens to.
 * Upsampling interpolates linearly.
 */
export function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (!(fromRate > 0) || !(toRate > 0)) throw new Error("Sample rate must be positive");
  if (fromRate === toRate) return input.slice();

  const outLength = Math.floor((input.length * toRate) / fromRate);
  const out = new Float32Array(outLength);
  const step = fromRate / toRate;

  if (step < 1) {
    const last = input.length - 1;
    for (let i = 0; i < outLength; i++) {
      const position = i * step;
      const lower = Math.floor(position);
      const upper = Math.min(lower + 1, last);
      const fraction = position - lower;
      out[i] = input[lower] * (1 - fraction) + input[upper] * fraction;
    }
    return out;
  }

  for (let i = 0; i < outLength; i++) {
    const start = Math.max(0, i * step - step / 2);
    const end = Math.min(input.length, i * step + step / 2);
    let sum = 0;
    for (let j = Math.floor(start); j < Math.ceil(end); j++) {
      const weight = Math.min(j + 1, end) - Math.max(j, start);
      sum += input[j] * weight;
    }
    out[i] = sum / (end - start);
  }
  return out;
}

/** Joins captured chunks (each an array of per-channel buffers) into Whisper-ready audio. */
export function prepareWhisperInput(
  chunks: readonly (readonly Float32Array[])[],
  captureRate: number,
): Float32Array {
  if (chunks.length === 0) return new Float32Array(0);
  const channelCount = chunks[0].length;
  const joined: Float32Array[] = [];
  for (let c = 0; c < channelCount; c++) {
    const parts = chunks.map((chunk) => chunk[c]);
    const total = parts.reduce((n, p) => n + p.length, 0);
    const channel = new Float32Array(total);
    let offset = 0;
    for (const part of parts) {
      channel.set(part, offset);
      offset += part.length;
    }
    joined.push(channel);
  }
  return resample(downmixToMono(joined), captureRate, WHISPER_SAMPLE_RATE);
}
