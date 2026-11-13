/** Configuration and verbatim result views, both owned by this external plugin. */
import { useEffect, useState } from 'react'
import { SettingsForm, SettingsValueField } from '@deepseek-ai/dsh-client-ui-primitives'
import type { PropsLocale, PropsRuntime, InjectFace } from '@deepseek-ai/dsh-client-ui-slots'
import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client'
import type {} from '@deepseek-ai/dsh-client-ui-chat/client'
import type { SessionId } from '@deepseek-ai/dsh-session/types'
import type { AudioCatalog, AudioSavedTranscript } from '../types.ts'
import type { audioForm } from './form.ts'
import type { NS } from './locales.ts'
import { audioPlaybackUrl } from '../core/playback-route.ts'
import type { AudioTurnItem } from './turn.ts'
import { AudioPlayer } from './player.tsx'
import css from './style.module.css'

/** Actions and framework-owned store supplied to the plugin configuration slot. */
export interface SettingsFace {
  hooks: { audioSettings: ReturnType<typeof audioForm>['store'] }
  edit: ReturnType<typeof audioForm>['actions']['edit']
  resetField: ReturnType<typeof audioForm>['actions']['resetField']
  save: () => void
  discard: () => void
  catalog: (signal: AbortSignal) => Promise<AudioCatalog>
}

/**
 * Render a staged form, with catalogue lookup only on an explicit button click.
 * @param props - locale, form actions, and framework-bound settings snapshot.
 * @returns plugin configuration page.
 */
export function AudioSettingsView(props: PropsRuntime<'plugins.bundle.config'> & PropsLocale<typeof NS> & InjectFace<SettingsFace>) {
  const { t } = props
  const state = props.useAudioSettings(value => value)
  const [catalog, setCatalog] = useState<AudioCatalog>()
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [request, setRequest] = useState<AbortController>()
  useEffect(() => () => { request?.abort() }, [request, state.fields.baseUrl.text])
  useEffect(() => { setCatalog(undefined); setChecking(false) }, [state.fields.baseUrl.text])
  const check = () => {
    const controller = new AbortController()
    setRequest(controller); setChecking(true); setError(''); setCatalog(undefined)
    void props.catalog(controller.signal).then((value) => {
      if (!controller.signal.aborted) setCatalog(value)
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause))
    }).finally(() => { if (!controller.signal.aborted) setChecking(false) })
  }
  if (props.view === 'summary') return t('description')
  return <section className={css.config}>
    <p>{t('description')}</p>
    <SettingsForm labels={{ unavailable: t('configUnavailable'), readOnly: t('readOnly'), saveFailed: t('saveFailed'), save: t('save'), saving: t('saving') }} state={state} onSave={props.save} onDiscard={props.discard}>
      {(['baseUrl', 'model', 'requestTimeoutMs', 'maxUploadBytes', 'maxResponseBytes', 'pageCharacters'] as const).map(field => <SettingsValueField key={field}
        id={`audio-${field}`} label={t(field)} overriddenLabel={t('overridden')} resetLabel={t('reset')} invalidLabel={t('invalid')}
        numeric={field !== 'baseUrl' && field !== 'model'} disabled={!state.writable}
        {...state.fields[field]} onEdit={(text) => { props.edit(field, text) }} onReset={() => { props.resetField(field) }} />)}
    </SettingsForm>
    <button type="button" onClick={check} disabled={checking || state.dirty || state.saving}>{t(checking ? 'checking' : 'check')}</button>
    {error ? <p role="alert">{error}</p> : null}
    {catalog ? <label>{t('choose')} <select value={state.fields.model.text} disabled={!state.writable} onChange={(event) => { props.edit('model', event.target.value) }}>
      <option value="">{t('choose')}</option>
      {catalog.models.map(model => <option key={model.key} value={model.key} disabled={!model.ready}>{model.name} — {t(model.ready ? 'ready' : 'notReady')}</option>)}
    </select></label> : null}
  </section>
}

/**
 * Render the complete, persisted original as text, independently of model summaries.
 * @param props - the Tool owner's call/result and this plugin's locale.
 * @returns expandable original or a localized running/error state.
 */
export function AudioTranscriptView(props: ToolCallViewProps & PropsLocale<typeof NS>) {
  if (props.phase !== 'result') return <p>{props.t('running')}</p>
  return <AudioTranscriptResult block={props.block} t={props.t} />
}

/** Render a validated, persisted result without consulting live host state.
 * @param props - settled result and localized copy.
 * @returns the complete original text or an explicit error view.
 */
export function AudioTranscriptResult(props: Pick<Extract<ToolCallViewProps, { phase: 'result' }>, 'block'> & PropsLocale<typeof NS>) {
  const block = props.block
  if (block.isError) return <section><strong>{props.t('failed')}</strong><pre className={css.transcript}>{block.content.flatMap(part => part.type === 'text' ? [part.text] : []).join('\n')}</pre></section>
  const meta = block.meta
  if (typeof meta !== 'object' || meta === null || !('audioTranscript' in meta) || meta.audioTranscript !== true
    || !('text' in meta) || typeof meta.text !== 'string' || !('file' in meta) || typeof meta.file !== 'string'
    || !('model' in meta) || typeof meta.model !== 'string') return <p>{props.t('unavailable')}</p>
  return <details open className={css.result}>
    <summary>{props.t('original')} · {meta.file} · {meta.model}</summary>
    <pre className={css.transcript}>{meta.text === '' ? props.t('empty') : meta.text}</pre>
  </details>
}

/** Session-owned history and media URL available to turn-tail cards. */
export interface AudioTurnOriginalsInjected {
  readonly sessionId: SessionId
  readonly savedTranscript: (source: string, signal: AbortSignal) => Promise<AudioSavedTranscript | null>
}

function preview(text: string): string {
  const firstLines = text.split('\n').slice(0, 3).join('\n')
  return firstLines.length > 600 ? `${firstLines.slice(0, 600)}…` : firstLines
}

/** Render one player and its original, failure, or running state.
 * @param props - persisted call state, owning session, saved-result reader, and locale.
 * @returns one audio card outside the collapsible tool process.
 */
export function AudioTurnOriginalCard(props: {
  readonly item: AudioTurnItem
  readonly sessionId: SessionId
  readonly savedTranscript: AudioTurnOriginalsInjected['savedTranscript']
  readonly t: PropsLocale<typeof NS>['t']
}) {
  const { item, sessionId, savedTranscript, t } = props
  const [previous, setPrevious] = useState<AudioSavedTranscript | null>()
  const [playbackFailed, setPlaybackFailed] = useState(false)
  const [copied, setCopied] = useState(false)
  const source = item.source ?? (item.attachmentId?.startsWith('sha256:') ? item.attachmentId.slice('sha256:'.length) : undefined)
  useEffect(() => {
    if (item.state !== 'error' || source === undefined) return
    const controller = new AbortController()
    void savedTranscript(source, controller.signal).then((value) => {
      if (!controller.signal.aborted) setPrevious(value)
    }).catch(() => {
      if (!controller.signal.aborted) setPrevious(null)
    })
    return () => { controller.abort() }
  }, [item.state, savedTranscript, source])
  useEffect(() => { setPlaybackFailed(false); setCopied(false) }, [item.attachmentId, item.callId])
  const text = item.state === 'success' ? item.text : previous?.text
  const model = item.model ?? previous?.model
  const sourceUrl = item.attachmentId === undefined ? undefined : audioPlaybackUrl(String(sessionId), item.attachmentId)
  const downloadUrl = sourceUrl === undefined ? undefined : `${sourceUrl}&download=1`
  const copy = () => {
    if (text === undefined) return
    void navigator.clipboard.writeText(text).then(() => { setCopied(true) })
  }
  return <article className={css.result} data-audio-original>
    <header className={css.cardHeader}>
      <strong>{item.file || t('audio')}</strong>
      {model === undefined ? null : <span>{model}</span>}
    </header>
    {sourceUrl === undefined
      ? <p className={css.muted}>{t('playbackUnavailable')}</p>
      : <AudioPlayer
        src={sourceUrl}
        label={t('original')}
        playLabel={t('play')}
        pauseLabel={t('pause')}
        seekLabel={t('seek')}
        onError={() => { setPlaybackFailed(true) }}
      />}
    {playbackFailed && downloadUrl !== undefined ? <p role="alert">{t('playbackFailed')} <a href={downloadUrl}>{t('download')}</a></p> : null}
    {item.state === 'running' ? <p role="status">{t('running')}</p> : null}
    {item.state === 'error' ? <p role="alert"><strong>{t('failed')}</strong>{item.error === undefined || item.error === '' ? null : ` ${item.error}`}</p> : null}
    {previous === null || text === undefined ? null : <section aria-label={previous === undefined ? t('original') : t('previousOriginal')}>
      {previous === undefined ? null : <strong>{t('previousOriginal')} · {previous.file} · {previous.model}</strong>}
      {text.length <= 600 && text.split('\n').length <= 8
        ? <pre className={css.transcript}>{text === '' ? t('empty') : text}</pre>
        : <details className={css.longTranscript}>
          <summary>{preview(text)}</summary>
          <pre className={css.transcript}>{text}</pre>
        </details>}
      <button type="button" onClick={copy}>{t(copied ? 'copied' : 'copy')}</button>
    </section>}
  </article>
}

/** Show each persisted audio state outside the collapsed tool process.
 * @param props - closing turn, owning session and localized labels.
 * @returns players and originals from this turn.
 */
export function AudioTurnOriginals(props: PropsRuntime<'conversation.chat.turnTail'> & PropsLocale<typeof NS> & InjectFace<AudioTurnOriginalsInjected>) {
  const items = props.turn.data.get('audio-originals')?.items ?? []
  const end = props.turn.end?.seq ?? props.seq
  return <div className={css.list}>{items.filter(item => item.seq <= end).map(item => <AudioTurnOriginalCard
    key={item.callId}
    item={item}
    sessionId={props.sessionId}
    savedTranscript={props.savedTranscript}
    t={props.t}
  />)}</div>
}
