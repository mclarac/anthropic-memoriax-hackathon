import { describe, expect, it } from "vitest";
import { SentencePlaybackQueue, type ClipPlayer } from "./playback-queue";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

/** Plays instantly unless `hold` is set, in which case the clip plays until released or stopped. */
class FakePlayer implements ClipPlayer<string> {
  played: string[] = [];
  stops = 0;
  hold = false;
  private release: (() => void) | null = null;

  play(clip: string): Promise<void> {
    this.played.push(clip);
    if (!this.hold) return Promise.resolve();
    return new Promise((resolve) => {
      this.release = resolve;
    });
  }

  finishCurrent() {
    this.release?.();
    this.release = null;
  }

  stop() {
    this.stops += 1;
    this.finishCurrent();
  }
}

describe("SentencePlaybackQueue", () => {
  it("plays sentences in index order even when synthesis finishes out of order", async () => {
    const player = new FakePlayer();
    const queue = new SentencePlaybackQueue(player);
    const first = deferred<string | null>();
    const second = deferred<string | null>();
    queue.add(0, 0, first.promise);
    queue.add(0, 1, second.promise);

    second.resolve("second");
    await tick();
    expect(player.played).toEqual([]);

    first.resolve("first");
    await tick();
    expect(player.played).toEqual(["first", "second"]);
  });

  it("accepts sentences that arrive out of index order", async () => {
    const player = new FakePlayer();
    const queue = new SentencePlaybackQueue(player);
    queue.add(0, 2, Promise.resolve("c"));
    queue.add(0, 0, Promise.resolve("a"));
    await tick();
    expect(player.played).toEqual(["a"]);
    queue.add(0, 1, Promise.resolve("b"));
    await tick();
    expect(player.played).toEqual(["a", "b", "c"]);
  });

  it("skips a sentence whose clip is null, such as one muted or failed", async () => {
    const player = new FakePlayer();
    const queue = new SentencePlaybackQueue(player);
    queue.add(0, 0, Promise.resolve("a"));
    queue.add(0, 1, Promise.resolve(null));
    queue.add(0, 2, Promise.resolve("c"));
    await tick();
    expect(player.played).toEqual(["a", "c"]);
  });

  it("plays turns in order and restarts indexes at 0 for each turn", async () => {
    const player = new FakePlayer();
    const queue = new SentencePlaybackQueue(player);
    queue.add(0, 0, Promise.resolve("t0s0"));
    queue.closeTurn(0);
    queue.add(1, 0, Promise.resolve("t1s0"));
    queue.add(1, 1, Promise.resolve("t1s1"));
    await tick();
    expect(player.played).toEqual(["t0s0", "t1s0", "t1s1"]);
  });

  it("moves on when a closed turn is missing a sentence", async () => {
    const player = new FakePlayer();
    const queue = new SentencePlaybackQueue(player);
    queue.add(0, 0, Promise.resolve("a"));
    queue.add(0, 2, Promise.resolve("never"));
    queue.closeTurn(0);
    queue.add(1, 0, Promise.resolve("next"));
    await tick();
    expect(player.played).toEqual(["a", "next"]);
  });

  it("reports speaking while audio is queued or playing and not after", async () => {
    const player = new FakePlayer();
    const states: boolean[] = [];
    const queue = new SentencePlaybackQueue(player, (speaking) => states.push(speaking));
    queue.add(0, 0, Promise.resolve("a"));
    await tick();
    expect(states).toEqual([true, false]);
  });

  describe("barge-in", () => {
    it("stops the current clip and drops everything queued for the turn", async () => {
      const player = new FakePlayer();
      player.hold = true;
      const states: boolean[] = [];
      const queue = new SentencePlaybackQueue(player, (s) => states.push(s));
      queue.add(0, 0, Promise.resolve("a"));
      queue.add(0, 1, Promise.resolve("b"));
      await tick();
      expect(player.played).toEqual(["a"]);

      queue.clear(0);
      await tick();
      expect(player.stops).toBe(1);
      expect(player.played).toEqual(["a"]);
      expect(states.at(-1)).toBe(false);
    });

    it("ignores sentences that arrive late for a cleared turn", async () => {
      const player = new FakePlayer();
      const queue = new SentencePlaybackQueue(player);
      queue.clear(0);
      queue.add(0, 0, Promise.resolve("late"));
      await tick();
      expect(player.played).toEqual([]);
    });

    it("drops a synthesis that finishes after the clear", async () => {
      const player = new FakePlayer();
      const queue = new SentencePlaybackQueue(player);
      const slow = deferred<string | null>();
      queue.add(0, 0, slow.promise);
      queue.clear(0);
      slow.resolve("too late");
      await tick();
      expect(player.played).toEqual([]);
    });

    it("plays the next turn normally after a clear", async () => {
      const player = new FakePlayer();
      player.hold = true;
      const queue = new SentencePlaybackQueue(player);
      queue.add(0, 0, Promise.resolve("old"));
      await tick();
      queue.clear(0);
      player.hold = false;
      queue.add(1, 0, Promise.resolve("reply"));
      await tick();
      expect(player.played).toEqual(["old", "reply"]);
    });
  });
});
