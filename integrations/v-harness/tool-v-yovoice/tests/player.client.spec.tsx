import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  WAVEFORM_BINS, WAVEFORM_MAX_BYTES, WAVEFORM_MAX_SECONDS, WaveformSeek, formatMediaTime, waveformPeaks,
} from '../src/client/player.tsx'

it('normalizes real PCM channels into bounded waveform bins', () => {
  const left = new Float32Array([0, 0.25, -0.5, 1, 0, -0.25, 0.5, 0])
  const right = new Float32Array([0, 0, 0.25, -0.75, 0, 0.5, -0.25, 0])
  const peaks = waveformPeaks([left, right], left.length, 4)
  expect(peaks[0]).toBe(0.25)
  expect(peaks[1]).toBe(1)
  expect(peaks[2]).toBe(0.5)
  expect(peaks[3]).toBe(0.5)
  expect(waveformPeaks([], 8, 4)).toEqual([])
  expect(waveformPeaks([new Float32Array(8)], 8, 4)).toEqual([0, 0, 0, 0])
})

it('keeps waveform decoding bounded and formats elapsed time', () => {
  expect(WAVEFORM_MAX_BYTES).toBe(20 * 1024 * 1024)
  expect(WAVEFORM_MAX_SECONDS).toBe(600)
  expect(WAVEFORM_BINS).toBe(160)
  expect(formatMediaTime(0)).toBe('0:00')
  expect(formatMediaTime(65.9)).toBe('1:05')
  expect(formatMediaTime(Number.NaN)).toBe('0:00')
})

it('renders an accessible waveform slider with played and unplayed regions', () => {
  const html = renderToStaticMarkup(<WaveformSeek
    peaks={[0.2, 0.4, 1, 0.5]}
    current={5}
    duration={10}
    label="Audio progress"
    onSeek={() => {}}
  />)
  expect(html).toContain('role="slider"')
  expect(html).toContain('aria-valuemax="10"')
  expect(html).toContain('aria-valuenow="5"')
  expect(html).toContain('waveformBase')
  expect(html).toContain('waveformPlayed')
})
