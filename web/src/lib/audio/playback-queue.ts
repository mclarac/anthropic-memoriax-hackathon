export interface ClipPlayer<Clip> {
  /** Resolves when the clip has finished or was cut short by stop(). */
  play(clip: Clip): Promise<void>;
  stop(): void;
}

type ClipLoad<Clip> = Promise<Clip | null>;

/**
 * Plays synthesized sentences strictly by (turn, index) while their audio may be
 * produced in any order. A null clip means "nothing to play" (muted or synthesis
 * failed) and is skipped without breaking the order. Clip promises must not reject;
 * the loader reports its own failures and resolves null.
 */
export class SentencePlaybackQueue<Clip> {
  private readonly pending = new Map<number, Map<number, ClipLoad<Clip>>>();
  private readonly closedTurns = new Set<number>();
  private cursor = { turn: 0, next: 0 };
  private discardedThrough = -1;
  private generation = 0;
  private draining = false;
  private speaking = false;

  constructor(
    private readonly player: ClipPlayer<Clip>,
    private readonly onSpeakingChange: (speaking: boolean) => void = () => {},
  ) {}

  add(turn: number, index: number, clip: ClipLoad<Clip>): void {
    if (turn <= this.discardedThrough) return;
    let sentences = this.pending.get(turn);
    if (!sentences) {
      sentences = new Map();
      this.pending.set(turn, sentences);
    }
    sentences.set(index, clip);
    void this.drain();
  }

  /** No more sentences will arrive for this turn, so a gap in it can be skipped. */
  closeTurn(turn: number): void {
    this.closedTurns.add(turn);
    void this.drain();
  }

  /** Barge-in: silence the current clip and forget every turn up to and including throughTurn. */
  clear(throughTurn: number): void {
    this.discardedThrough = Math.max(this.discardedThrough, throughTurn);
    for (const turn of [...this.pending.keys()]) {
      if (turn <= this.discardedThrough) this.pending.delete(turn);
    }
    for (const turn of [...this.closedTurns]) {
      if (turn <= this.discardedThrough) this.closedTurns.delete(turn);
    }
    this.generation += 1;
    this.player.stop();
    void this.drain();
  }

  private takeNext(): ClipLoad<Clip> | undefined {
    if (this.cursor.turn <= this.discardedThrough) {
      this.cursor = { turn: this.discardedThrough + 1, next: 0 };
    }
    for (;;) {
      const sentences = this.pending.get(this.cursor.turn);
      const clip = sentences?.get(this.cursor.next);
      if (clip) {
        sentences?.delete(this.cursor.next);
        return clip;
      }
      if (!this.closedTurns.has(this.cursor.turn)) return undefined;
      this.pending.delete(this.cursor.turn);
      this.closedTurns.delete(this.cursor.turn);
      this.cursor = { turn: this.cursor.turn + 1, next: 0 };
    }
  }

  private setSpeaking(speaking: boolean): void {
    if (this.speaking === speaking) return;
    this.speaking = speaking;
    this.onSpeakingChange(speaking);
  }

  private async drain(): Promise<void> {
    if (this.draining) return;
    this.draining = true;
    try {
      for (;;) {
        const generation = this.generation;
        const load = this.takeNext();
        if (!load) break;
        this.setSpeaking(true);
        const clip = await load;
        if (generation !== this.generation) continue;
        if (clip !== null) await this.player.play(clip);
        if (generation === this.generation) this.cursor.next += 1;
      }
    } finally {
      this.draining = false;
      this.setSpeaking(false);
    }
  }
}
