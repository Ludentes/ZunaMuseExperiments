/**
 * Fixed-size ring buffer backed by Float32Array.
 * Used for waveform display — new samples overwrite oldest.
 */
export class RingBuffer {
  private buffer: Float32Array;
  private writePos: number = 0;
  private _filled: boolean = false;

  constructor(public readonly capacity: number) {
    this.buffer = new Float32Array(capacity);
  }

  /** Push new samples into the buffer. */
  push(samples: Float32Array | number[]): void {
    for (let i = 0; i < samples.length; i++) {
      this.buffer[this.writePos] = samples[i];
      this.writePos = (this.writePos + 1) % this.capacity;
      if (this.writePos === 0) this._filled = true;
    }
  }

  /** Get the buffer contents in chronological order (oldest first). */
  getOrdered(): Float32Array {
    if (!this._filled) {
      return this.buffer.subarray(0, this.writePos);
    }
    const result = new Float32Array(this.capacity);
    const tail = this.capacity - this.writePos;
    result.set(this.buffer.subarray(this.writePos), 0);
    result.set(this.buffer.subarray(0, this.writePos), tail);
    return result;
  }

  /** Number of samples currently stored. */
  get length(): number {
    return this._filled ? this.capacity : this.writePos;
  }

  clear(): void {
    this.buffer.fill(0);
    this.writePos = 0;
    this._filled = false;
  }
}
