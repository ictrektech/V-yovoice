/** Browser-owned microphone capture and canonical 16 kHz PCM16 WAV encoding. */

/** Capture failure whose message is localized by the dictation toolbar. */
export class RecordingError extends Error {
  constructor(readonly kind: 'unavailable' | 'permission' | 'empty' | 'cancelled' | 'interrupted' | 'deviceMissing') {
    super(kind)
    this.name = 'RecordingError'
  }
}

/** One microphone operation shared by the UI and its lifecycle owner. */
export interface RecordingCapture {
  /** Acquire the selected microphone and start capture. */
  start(onError?: (error: RecordingError) => void): Promise<void>
  /** Finish capture, resample to 16 kHz mono and encode PCM16 WAV. */
  stop(maxDurationSeconds: number): Promise<Uint8Array<ArrayBuffer>>
  /** Read the current microphone RMS amplitude. */
  amplitude(): number
  /** Release tracks, recorder and Web Audio resources. */
  dispose(): Promise<void>
}

/**
 * Encode mono floating-point samples as canonical PCM16 WAV.
 * @param samples - native-resampled 16 kHz mono samples.
 * @returns complete little-endian WAV bytes.
 */
export function encodeWave(samples: Float32Array): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(44 + samples.length * 2)
  const view = new DataView(bytes.buffer)
  const text = (at: number, value: string): void => {
    for (let index = 0; index < value.length; index++) bytes[at + index] = value.charCodeAt(index)
  }
  text(0, 'RIFF')
  view.setUint32(4, bytes.length - 8, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, 16_000, true)
  view.setUint32(28, 32_000, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  for (let index = 0; index < samples.length; index++) {
    const sample = Math.max(-1, Math.min(1, samples[index] ?? 0))
    view.setInt16(44 + index * 2, Math.round(sample * (sample < 0 ? 32_768 : 32_767)), true)
  }
  return bytes
}

/**
 * Encode a complete recording for the authenticated JSON Remote request.
 * @param bytes - complete WAV recording.
 * @returns base64 without a data URL prefix.
 */
export function audioBase64(bytes: Uint8Array): string {
  let text = ''
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    text += String.fromCharCode(...bytes.subarray(offset, offset + 8192))
  }
  return btoa(text)
}

/** One browser microphone acquisition with idempotent resource release. */
export class Recording implements RecordingCapture {
  private stream: MediaStream | undefined
  private recorder: MediaRecorder | undefined
  private context: AudioContext | undefined
  private analyser: AnalyserNode | undefined
  private readonly samples = new Float32Array(256)
  private chunks: Blob[] = []
  private readonly lifetime = new AbortController()
  private disposal: Promise<void> | undefined

  constructor(private readonly onDispose: () => void) {}

  /**
   * Acquire the system-default microphone and start recording.
   * @param onError - receives device or recorder interruption.
   * @returns after MediaRecorder has started.
   */
  async start(onError?: (error: RecordingError) => void): Promise<void> {
    if (typeof MediaRecorder === 'undefined') throw new RecordingError('unavailable')
    const devices = (navigator as Partial<Navigator>).mediaDevices
    if (devices === undefined) throw new RecordingError('unavailable')
    let stream: MediaStream
    try {
      stream = await devices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      })
    } catch (error) {
      if (error instanceof DOMException) {
        if (error.name === 'NotAllowedError') throw new RecordingError('permission')
        if (error.name === 'NotFoundError' || error.name === 'OverconstrainedError') {
          throw new RecordingError('deviceMissing')
        }
      }
      throw error
    }
    if (this.lifetime.signal.aborted) {
      stream.getTracks().forEach((track) => { track.stop() })
      throw new RecordingError('cancelled')
    }

    this.stream = stream
    try {
      this.context = new AudioContext()
      this.analyser = this.context.createAnalyser()
      this.analyser.fftSize = this.samples.length
      this.context.createMediaStreamSource(stream).connect(this.analyser)
      for (const track of stream.getTracks()) {
        track.addEventListener('ended', () => { this.interrupted(onError) }, { signal: this.lifetime.signal })
      }
      this.recorder = new MediaRecorder(stream)
      this.recorder.ondataavailable = (event) => {
        if (!this.lifetime.signal.aborted && event.data.size > 0) this.chunks.push(event.data)
      }
      this.recorder.onerror = () => { this.interrupted(onError) }
      this.recorder.start()
    } catch (error) {
      await this.dispose()
      throw error
    }
  }

  /** Read the current microphone signal as RMS amplitude. */
  amplitude(): number {
    if (this.analyser === undefined) return 0
    this.analyser.getFloatTimeDomainData(this.samples)
    let sum = 0
    for (const sample of this.samples) sum += sample * sample
    return Math.sqrt(sum / this.samples.length)
  }

  /**
   * Finish capture and resample to the Host's canonical format.
   * @param maxDurationSeconds - truncate timer overshoot to the configured limit.
   * @returns complete PCM16 WAV bytes.
   */
  async stop(maxDurationSeconds: number): Promise<Uint8Array<ArrayBuffer>> {
    const recorder = this.recorder
    const context = this.context
    if (recorder === undefined || context === undefined || recorder.state !== 'recording') {
      await this.dispose()
      throw new RecordingError('empty')
    }
    try {
      await new Promise<void>((resolve, reject) => {
        recorder.onstop = () => { resolve() }
        recorder.onerror = () => { reject(new RecordingError('empty')) }
        recorder.stop()
      })
      this.stream?.getTracks().forEach((track) => { track.stop() })
      this.lifetime.signal.throwIfAborted()
      const blob = new Blob(this.chunks, { type: recorder.mimeType })
      if (blob.size === 0) throw new RecordingError('empty')
      const decoded = await context.decodeAudioData(await blob.arrayBuffer())
      this.lifetime.signal.throwIfAborted()
      const frames = Math.max(1, Math.floor(Math.min(decoded.duration, maxDurationSeconds) * 16_000))
      const offline = new OfflineAudioContext(1, frames, 16_000)
      const source = offline.createBufferSource()
      source.buffer = decoded
      source.connect(offline.destination)
      source.start()
      const rendered = await offline.startRendering()
      this.lifetime.signal.throwIfAborted()
      return encodeWave(rendered.getChannelData(0))
    } finally {
      await this.dispose()
    }
  }

  /** Release this recording and invalidate pending permission grants. */
  dispose(): Promise<void> {
    if (this.disposal === undefined) {
      const closing = Promise.withResolvers<void>()
      this.disposal = closing.promise
      void this.release().then(closing.resolve, closing.reject)
    }
    return this.disposal
  }

  private interrupted(onError: ((error: RecordingError) => void) | undefined): void {
    if (this.lifetime.signal.aborted) return
    void this.dispose().catch(() => undefined)
    try {
      onError?.(new RecordingError('interrupted'))
    } catch (error) {
      console.error('Dictation recording error handler failed', error)
    }
  }

  private async release(): Promise<void> {
    this.lifetime.abort(new RecordingError('cancelled'))
    if (this.recorder?.state === 'recording') this.recorder.stop()
    this.stream?.getTracks().forEach((track) => { track.stop() })
    this.stream = undefined
    const context = this.context
    this.context = undefined
    this.analyser = undefined
    this.chunks = []
    try {
      if (context !== undefined && context.state !== 'closed') await context.close()
    } finally {
      this.onDispose()
    }
  }
}
