/** Compact single-audio player with a real waveform that degrades to a progress bar. */
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import css from './style.module.css'

/** Largest source decoded for a waveform visualization. */
export const WAVEFORM_MAX_BYTES = 20 * 1024 * 1024
/** Longest source decoded for a waveform visualization. */
export const WAVEFORM_MAX_SECONDS = 10 * 60
/** Number of visible peak bins. */
export const WAVEFORM_BINS = 160

const waveformCache = new Map<string, readonly number[]>()
const WAVEFORM_CACHE_ENTRIES = 24

/** Format elapsed media time without locale-specific punctuation.
 * @param seconds - media position.
 * @returns minute:second text.
 */
export function formatMediaTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const whole = Math.floor(seconds)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

/** Compute normalized waveform peak bins from decoded channel data.
 * @param channels - decoded PCM channels.
 * @param length - decoded frame count.
 * @param bins - requested visual bins.
 * @returns normalized peaks in [0, 1].
 */
export function waveformPeaks(channels: readonly Float32Array[], length: number, bins = WAVEFORM_BINS): number[] {
  if (channels.length === 0 || length <= 0 || bins <= 0) return []
  const output = new Array<number>(bins).fill(0)
  const width = Math.ceil(length / bins)
  let maximum = 0
  for (let bin = 0; bin < bins; bin++) {
    const start = bin * width
    const end = Math.min(length, start + width)
    const stride = Math.max(1, Math.floor((end - start) / 2048))
    let peak = 0
    for (const channel of channels) {
      for (let index = start; index < end; index += stride) {
        peak = Math.max(peak, Math.abs(channel[index] ?? 0))
      }
    }
    output[bin] = peak
    maximum = Math.max(maximum, peak)
  }
  return maximum === 0 ? output : output.map(peak => peak / maximum)
}

function remember(src: string, peaks: readonly number[]): void {
  if (waveformCache.size >= WAVEFORM_CACHE_ENTRIES) {
    const oldest = waveformCache.keys().next().value
    if (oldest !== undefined) waveformCache.delete(oldest)
  }
  waveformCache.set(src, peaks)
}

async function decodeWaveform(src: string, duration: number, signal: AbortSignal): Promise<readonly number[] | null> {
  const cached = waveformCache.get(src)
  if (cached !== undefined) {
    waveformCache.delete(src)
    waveformCache.set(src, cached)
    return cached
  }
  if (duration <= 0 || duration > WAVEFORM_MAX_SECONDS) return null
  const head = await fetch(src, { method: 'HEAD', credentials: 'same-origin', signal })
  if (!head.ok) return null
  const length = Number(head.headers.get('content-length'))
  if (!Number.isSafeInteger(length) || length <= 0 || length > WAVEFORM_MAX_BYTES) return null
  const response = await fetch(src, { credentials: 'same-origin', signal })
  if (!response.ok) return null
  const data = await response.arrayBuffer()
  signal.throwIfAborted()
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(data)
    signal.throwIfAborted()
    if (decoded.duration > WAVEFORM_MAX_SECONDS) return null
    const channels = Array.from(
      { length: decoded.numberOfChannels },
      (_, index) => decoded.getChannelData(index),
    )
    const peaks = waveformPeaks(channels, decoded.length)
    remember(src, peaks)
    return peaks
  } finally {
    await context.close()
  }
}

function pathFor(peaks: readonly number[], from: number, to: number): string {
  if (peaks.length === 0 || from >= to) return ''
  const count = peaks.length
  let path = ''
  for (let index = from; index < to; index++) {
    const x = count <= 1 ? 0 : index / (count - 1) * 1000
    const amplitude = 2 + Math.max(0, peaks[index] ?? 0) * 36
    path += `M${x.toFixed(2)} ${(20 - amplitude / 2).toFixed(2)}v${amplitude.toFixed(2)}`
  }
  return path
}

/** Waveform-styled slider with pointer, hover and keyboard seeking. */
export function WaveformSeek(props: {
  readonly peaks: readonly number[]
  readonly current: number
  readonly duration: number
  readonly label: string
  readonly onSeek: (seconds: number) => void
}) {
  const [hover, setHover] = useState<number>()
  const ratio = props.duration <= 0 ? 0 : Math.min(1, Math.max(0, props.current / props.duration))
  const split = Math.round(ratio * props.peaks.length)
  const seekAt = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const value = rect.width <= 0 ? 0 : Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
    props.onSeek(value * props.duration)
    return value
  }
  const key = (event: KeyboardEvent<SVGSVGElement>) => {
    const step = event.shiftKey ? 15 : 5
    let next: number | undefined
    if (event.key === 'ArrowLeft') next = props.current - step
    else if (event.key === 'ArrowRight') next = props.current + step
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = props.duration
    if (next === undefined) return
    event.preventDefault()
    props.onSeek(Math.min(props.duration, Math.max(0, next)))
  }
  return <div className={css.waveformViewport}>
    <svg
      className={css.waveform}
      viewBox="0 0 1000 40"
      preserveAspectRatio="none"
      role="slider"
      tabIndex={0}
      aria-label={props.label}
      aria-valuemin={0}
      aria-valuemax={props.duration}
      aria-valuenow={props.current}
      aria-valuetext={`${formatMediaTime(props.current)} / ${formatMediaTime(props.duration)}`}
      onKeyDown={key}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId)
        setHover(seekAt(event))
      }}
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect()
        setHover(rect.width <= 0 ? undefined : (event.clientX - rect.left) / rect.width)
      }}
      onPointerUp={(event) => { seekAt(event); setHover(undefined) }}
      onPointerLeave={() => { setHover(undefined) }}
    >
      <path className={css.waveformBase} d={pathFor(props.peaks, 0, props.peaks.length)} />
      <path className={css.waveformPlayed} d={pathFor(props.peaks, 0, split)} />
    </svg>
    {hover === undefined || !Number.isFinite(hover) ? null : <span className={css.waveformTooltip}
      style={{ left: `${Math.min(100, Math.max(0, hover * 100))}%` }}>
      {formatMediaTime(hover * props.duration)}
    </span>}
  </div>
}

/** Playback and seek control for one persisted audio source. */
export function AudioPlayer(props: {
  readonly src: string
  readonly label: string
  readonly playLabel: string
  readonly pauseLabel: string
  readonly seekLabel: string
  readonly onError: () => void
}) {
  const media = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [peaks, setPeaks] = useState<readonly number[] | null>()
  useEffect(() => {
    setPlaying(false)
    setCurrent(0)
    setDuration(0)
    setPeaks(undefined)
  }, [props.src])
  useEffect(() => {
    if (duration <= 0) return
    const controller = new AbortController()
    void decodeWaveform(props.src, duration, controller.signal).then((value) => {
      if (!controller.signal.aborted) setPeaks(value ?? null)
    }).catch(() => {
      if (!controller.signal.aborted) setPeaks(null)
    })
    return () => { controller.abort() }
  }, [duration, props.src])
  const syncDuration = (audio: HTMLAudioElement) => {
    setDuration(Number.isFinite(audio.duration) ? audio.duration : 0)
  }
  const seek = (seconds: number) => {
    if (media.current !== null) media.current.currentTime = seconds
    setCurrent(seconds)
  }
  const toggle = async () => {
    const audio = media.current
    if (audio === null) return
    if (audio.paused) {
      try {
        await audio.play()
      } catch {
        props.onError()
      }
    } else {
      audio.pause()
    }
  }
  const progress = duration <= 0 ? 0 : Math.min(100, Math.max(0, current / duration * 100))
  const progressStyle = { '--audio-progress': `${progress}%` } as CSSProperties
  return <div className={css.player}>
    <audio
      ref={media}
      aria-label={props.label}
      className={css.media}
      preload="metadata"
      src={props.src}
      onDurationChange={(event) => { syncDuration(event.currentTarget) }}
      onLoadedMetadata={(event) => { syncDuration(event.currentTarget) }}
      onTimeUpdate={(event) => { setCurrent(event.currentTarget.currentTime) }}
      onPlay={() => { setPlaying(true) }}
      onPause={() => { setPlaying(false) }}
      onEnded={(event) => {
        setPlaying(false)
        setCurrent(event.currentTarget.duration)
      }}
      onError={props.onError}
    />
    <div className={css.waveformViewport} data-waveform={peaks === undefined ? 'loading' : peaks === null ? 'fallback' : 'ready'}>
      {peaks === undefined || peaks === null
        ? <input
          type="range"
          className={css.progress}
          aria-label={props.seekLabel}
          min="0"
          max={duration || 0}
          step="0.01"
          value={Math.min(current, duration || 0)}
          style={progressStyle}
          disabled={duration <= 0}
          onChange={(event) => { seek(Number(event.currentTarget.value)) }}
        />
        : <WaveformSeek peaks={peaks} current={current} duration={duration} label={props.seekLabel} onSeek={seek} />}
    </div>
    <div className={css.controlsRow}>
      <span className={css.time}>{formatMediaTime(current)}</span>
      <button
        type="button"
        className={css.playButton}
        aria-label={playing ? props.pauseLabel : props.playLabel}
        aria-pressed={playing}
        onClick={() => { void toggle() }}
      >
        <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16">
          {playing
            ? <><rect x="3" y="2" width="3.5" height="12" rx="1" /><rect x="9.5" y="2" width="3.5" height="12" rx="1" /></>
            : <path d="M4 2.3v11.4c0 .8.9 1.3 1.6.8l8.2-5.7c.6-.4.6-1.2 0-1.6L5.6 1.5C4.9 1 4 1.5 4 2.3Z" />}
        </svg>
      </button>
      <span className={`${css.time} ${css.remaining}`}>-{formatMediaTime(Math.max(0, duration - current))}</span>
    </div>
  </div>
}
