/** Composer microphone that turns one transient recording into reviewable draft text. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { InjectFace, PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type { TokenSpan } from '@deepseek-ai/dsh-client-ui-conversation/client'
import { Button, IconCloseOutlineRegular, IconMicrophoneOutlineRegular, IconStopFillRegular, StateDot, Tooltip } from '@deepseek-ai/dsh-client-ui-primitives'
import type { DictationLimits, DictationRequest, DictationResult } from '../types.ts'
import { audioBase64, RecordingError, type Recording, type RecordingCapture } from './recording.ts'
import type { NS } from './locales.ts'
import css from './style.module.css'

/** Host calls injected without exposing a Cordis Context to React. */
export interface DictationActions {
  /** Read the current profile-owned duration and byte bounds. */
  loadLimits: (signal: AbortSignal) => Promise<DictationLimits>
  /** @returns one microphone operation owned by the plugin lifecycle. */
  createRecording: () => Recording
  /** Recognize one complete recording; unrelated to Session submission. */
  transcribe: (request: DictationRequest, signal: AbortSignal) => Promise<DictationResult>
}

/** Composer-owned draft actions and plugin-owned microphone calls. */
export type DictationControlProps = Pick<
  PropsRuntime<'conversation.input.activity'>,
  'sessionId' | 'inputActions' | 'locked' | 'onActiveChange'
> & PropsLocale<typeof NS> & InjectFace<DictationActions>

type Phase = 'idle' | 'requesting' | 'recording' | 'transcribing' | 'feedback'

interface ActiveRecording {
  readonly capture: Recording
  readonly abort: AbortController
  span?: TokenSpan
  limits?: DictationLimits
  phase: 'requesting' | 'recording' | 'transcribing'
  timer?: ReturnType<typeof setTimeout>
}

async function disposeRecording(capture: RecordingCapture): Promise<void> {
  try {
    await capture.dispose()
  } catch (error) {
    // Tracks stop before AudioContext.close(); cleanup failure must not replace the recognition result.
    void error
  }
}

function failureText(failure: unknown, t: PropsLocale<typeof NS>['t']): string {
  if (failure instanceof RecordingError) {
    switch (failure.kind) {
      case 'unavailable': return t('dictationUnavailable')
      case 'permission': return t('dictationPermission')
      case 'empty': return t('empty')
      case 'cancelled': return t('dictationCancelled')
      case 'interrupted': return t('dictationInterrupted')
      case 'deviceMissing': return t('dictationDeviceMissing')
    }
  }
  return t('dictationFailed', { message: failure instanceof Error ? failure.message : String(failure) })
}

function Waveform({ capture, label }: { readonly capture: RecordingCapture | undefined; readonly label: string }) {
  const svg = useRef<SVGSVGElement>(null)
  useEffect(() => {
    const lines = Array.from(svg.current?.querySelectorAll('line') ?? [])
      .reverse()
      .map(element => ({ element, level: 0 }))
    let frame = 0
    let previous = -Infinity
    const draw = (now: number): void => {
      if (now - previous >= 50) {
        previous = now
        let next = capture?.amplitude() ?? 0
        for (const line of lines) {
          const previousLevel = line.level
          line.level = next
          next = previousLevel
          const height = 1 + Math.min(1, line.level * 5) * 17
          line.element.setAttribute('y1', String(20 - height))
          line.element.setAttribute('y2', String(20 + height))
        }
      }
      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => { cancelAnimationFrame(frame) }
  }, [capture])
  return <svg ref={svg} className={css.dictationWave} viewBox="0 0 640 40"
    preserveAspectRatio="none" role="img" aria-label={label}>
    {Array.from({ length: 80 }, (_, index) => <line key={index} x1={index * 8 + 4} x2={index * 8 + 4}
      y1="19" y2="21" stroke="currentColor" strokeWidth="3" strokeLinecap="round"
      opacity={0.25 + index / 120} />)}
  </svg>
}

/** Render the compact microphone or its requesting, recording, transcription and retry states. */
export function DictationControl({
  sessionId, inputActions, locked, onActiveChange, loadLimits, createRecording, transcribe, t,
}: DictationControlProps) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState('')
  const current = useRef<ActiveRecording>()
  const generation = useRef(0)
  const expanded = phase !== 'idle'

  useLayoutEffect(() => {
    onActiveChange(expanded)
    return () => { onActiveChange(false) }
  }, [expanded, onActiveChange])

  const cancel = (): void => {
    generation.current++
    const active = current.current
    current.current = undefined
    if (active !== undefined) {
      clearTimeout(active.timer)
      active.abort.abort()
      void disposeRecording(active.capture)
    }
    setPending('')
    setMessage('')
    setPhase('idle')
  }

  const feedback = (text: string): void => {
    setMessage(text)
    setPhase('feedback')
  }

  const finish = async (): Promise<void> => {
    const active = current.current
    if (active === undefined || active.phase !== 'recording' || active.limits === undefined || active.span === undefined) {
      return
    }
    active.phase = 'transcribing'
    const run = generation.current
    clearTimeout(active.timer)
    setPhase('transcribing')
    try {
      const audio = await active.capture.stop(active.limits.maxSeconds)
      if (run !== generation.current) return
      if (audio.byteLength > active.limits.maxAudioBytes) {
        feedback(t('tooLarge'))
        return
      }
      const result = await transcribe({ audioBase64: audioBase64(audio) }, active.abort.signal)
      if (run !== generation.current) return
      if (result.text === '') {
        feedback(t('empty'))
        return
      }
      if (!inputActions.insertText(result.text, active.span)) {
        setPending(result.text)
        feedback(t('conflict'))
        return
      }
      setPhase('idle')
    } catch (failure) {
      await disposeRecording(active.capture)
      if (run === generation.current) feedback(failureText(failure, t))
    } finally {
      if (run === generation.current) current.current = undefined
    }
  }

  const start = async (): Promise<void> => {
    if (locked || current.current !== undefined) return
    const run = ++generation.current
    const active: ActiveRecording = {
      capture: createRecording(),
      abort: new AbortController(),
      phase: 'requesting',
    }
    current.current = active
    setMessage('')
    setPending('')
    setPhase('requesting')
    try {
      const limits = await loadLimits(active.abort.signal)
      if (run !== generation.current || current.current !== active) return
      active.limits = limits
      active.span = inputActions.captureInsertion()
      await active.capture.start((failure) => {
        if (run !== generation.current || current.current !== active || active.phase === 'transcribing') return
        current.current = undefined
        clearTimeout(active.timer)
        active.abort.abort()
        feedback(failureText(failure, t))
      })
      if (run !== generation.current || current.current !== active) return
      active.phase = 'recording'
      setPhase('recording')
      active.timer = setTimeout(() => { void finish() }, limits.maxSeconds * 1000)
    } catch (failure) {
      await disposeRecording(active.capture)
      if (run === generation.current) {
        current.current = undefined
        feedback(failureText(failure, t))
      }
    }
  }

  useEffect(() => {
    setPending('')
    setMessage('')
    setPhase('idle')
    const blur = (): void => {
      if (current.current?.phase === 'recording') cancel()
    }
    const visibility = (): void => {
      if (document.hidden && current.current !== undefined && current.current.phase !== 'transcribing') cancel()
    }
    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && current.current !== undefined) {
        event.preventDefault()
        cancel()
      }
    }
    window.addEventListener('blur', blur)
    document.addEventListener('visibilitychange', visibility)
    document.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('blur', blur)
      document.removeEventListener('visibilitychange', visibility)
      document.removeEventListener('keydown', escape)
      generation.current++
      const active = current.current
      current.current = undefined
      if (active !== undefined) {
        clearTimeout(active.timer)
        active.abort.abort()
        void disposeRecording(active.capture)
      }
    }
  }, [sessionId])

  if (!expanded) {
    return <>
      <Tooltip label={t('dictate')} side="top" portal>
        <span className={css.dictationAnchor}>
          <Button className={css.dictationTrigger} size="sm" disabled={locked}
            aria-label={t('start')} onMouseDown={(event) => { event.preventDefault() }}
            onClick={() => { void start() }}>
            <IconMicrophoneOutlineRegular size={18} />
          </Button>
        </span>
      </Tooltip>
    </>
  }

  return <div className={css.dictationRow} data-dictation-phase={phase}>
    <Button type="button" className={css.dictationRound} size="sm"
      aria-label={pending === '' ? t('cancel') : t('discard')} onClick={cancel}>
      <IconCloseOutlineRegular size={14} />
    </Button>
    {phase === 'recording'
      ? <Waveform capture={current.current?.capture} label={t('recording')} />
      : <span className={css.dictationMessage} role="status" title={pending || message}>
        {(phase === 'requesting' || phase === 'transcribing') && <StateDot state="ongoing" />}
        {phase === 'feedback' ? message : t(phase === 'requesting' ? 'requesting' : 'transcribing')}
      </span>}
    {phase === 'recording' ? <Button type="button" className={css.dictationRound} size="sm"
      aria-label={t('stop')} onClick={() => { void finish() }}>
      <IconStopFillRegular size={14} />
    </Button> : null}
    {phase === 'feedback' ? (pending === ''
      ? <Button type="button" className={css.dictationRound} size="sm" aria-label={t('retryRecording')}
        disabled={locked} onClick={() => { void start() }}>
        <IconMicrophoneOutlineRegular size={18} />
      </Button>
      : <Button className={css.dictationInlineAction} size="sm" type="button" onClick={() => {
        if (inputActions.insertText(pending, inputActions.captureInsertion())) {
          setPending('')
          setPhase('idle')
        }
      }}>{t('insert')}</Button>) : null}
  </div>
}
