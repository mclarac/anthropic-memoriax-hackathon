import { describe, expect, it } from "vitest";
import { downmixToMono, prepareWhisperInput, resample, WHISPER_SAMPLE_RATE } from "./resample";

function sine(freq: number, rate: number, seconds: number): Float32Array {
  const out = new Float32Array(Math.round(rate * seconds));
  for (let i = 0; i < out.length; i++) out[i] = Math.sin((2 * Math.PI * freq * i) / rate);
  return out;
}

describe("downmixToMono", () => {
  it("averages channels sample by sample", () => {
    const mono = downmixToMono([Float32Array.of(1, 0, -1), Float32Array.of(0, 0, 1)]);
    expect(Array.from(mono)).toEqual([0.5, 0, 0]);
  });

  it("returns a mono input unchanged in value", () => {
    expect(Array.from(downmixToMono([Float32Array.of(0.25, -0.5)]))).toEqual([0.25, -0.5]);
  });

  it("rejects channels of different lengths", () => {
    expect(() => downmixToMono([new Float32Array(3), new Float32Array(2)])).toThrow(/same length/);
  });

  it("rejects an empty channel list", () => {
    expect(() => downmixToMono([])).toThrow(/at least one channel/);
  });
});

describe("resample", () => {
  it("returns a copy when the rates match", () => {
    const input = Float32Array.of(0.1, 0.2, 0.3);
    const out = resample(input, 16000, 16000);
    expect(Array.from(out)).toEqual(Array.from(input));
    expect(out).not.toBe(input);
  });

  it("produces the expected length when downsampling 48 kHz to 16 kHz", () => {
    expect(resample(new Float32Array(48000), 48000, 16000)).toHaveLength(16000);
  });

  it("produces the expected length for a non-integer ratio (44.1 kHz)", () => {
    expect(resample(new Float32Array(44100), 44100, 16000)).toHaveLength(16000);
  });

  it("keeps a constant signal constant", () => {
    const out = resample(new Float32Array(480).fill(0.5), 48000, 16000);
    for (const v of out) expect(v).toBeCloseTo(0.5, 6);
  });

  it("preserves a 440 Hz sine when downsampling", () => {
    const out = resample(sine(440, 48000, 0.1), 48000, 16000);
    const expected = sine(440, 16000, 0.1);
    expect(out).toHaveLength(expected.length);
    // Averaging attenuates slightly at 440 Hz; shape and phase must still match closely.
    let worst = 0;
    for (let i = 1; i < out.length - 1; i++) worst = Math.max(worst, Math.abs(out[i] - expected[i]));
    expect(worst).toBeLessThan(0.1);
  });

  it("interpolates linearly when upsampling", () => {
    const out = resample(Float32Array.of(0, 1), 8000, 16000);
    expect(Array.from(out)).toEqual([0, 0.5, 1, 1]);
  });

  it("returns an empty array for empty input", () => {
    expect(resample(new Float32Array(0), 48000, 16000)).toHaveLength(0);
  });

  it("rejects non-positive rates", () => {
    expect(() => resample(new Float32Array(4), 0, 16000)).toThrow(/sample rate/i);
    expect(() => resample(new Float32Array(4), 48000, -1)).toThrow(/sample rate/i);
  });
});

describe("prepareWhisperInput", () => {
  it("concatenates chunks, downmixes to mono and resamples to 16 kHz", () => {
    const left = sine(300, 48000, 0.1);
    const right = sine(300, 48000, 0.1);
    const half = left.length / 2;
    const chunks = [
      [left.slice(0, half), right.slice(0, half)],
      [left.slice(half), right.slice(half)],
    ];
    const out = prepareWhisperInput(chunks, 48000);
    expect(out).toHaveLength(Math.floor((left.length * WHISPER_SAMPLE_RATE) / 48000));
  });

  it("returns an empty array when nothing was captured", () => {
    expect(prepareWhisperInput([], 48000)).toHaveLength(0);
  });
});
