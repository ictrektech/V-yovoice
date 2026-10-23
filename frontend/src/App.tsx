import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { api, formatBytes, AboutInfo, EnrolledSpeaker, HotwordSet, IdentifyResult, Model, VerifyResult } from './api'
import { Localized } from './i18n/Localized'
import { languageNames } from './i18n/messages'
import { setLanguageMode, useLanguage } from './i18n'
import type { LanguageMode } from './i18n/vosLocale'

type Tab = 'models' | 'asr' | 'tts' | 'hotwords' | 'speaker' | 'api'
type ApiTab = 'overview' | 'asr' | 'streaming' | 'tts' | 'creative' | 'workbench' | 'hotwords' | 'speaker' | 'models'

function RawText({ children }: { children: ReactNode }) {
  return <>{children}</>
}

const statusNames: Record<string, string> = { ready: '已就绪', verifying: '校验中', downloading: '下载中', not_installed: '未安装', failed: '失败' }

function EmptyReady({ kind }: { kind: 'ASR' | 'TTS' }) {
  const message = kind === 'ASR' ? '暂无已就绪的 ASR 模型' : '暂无已就绪的 TTS 模型'
  return <Localized><div className="empty-ready"><strong>{message}</strong><span>{window.__VVOICE_GATEWAY__ ? '请先在 V-Scheduler 接入对应的语音模型服务，再刷新此页面。' : '请先到“模型”页面安装一个模型，完成后即可在下拉列表中选择。'}</span></div></Localized>
}

function AboutDialog({ onClose }: { onClose: () => void }) {
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    api.about().then(setAbout).catch(value => setError(value instanceof Error ? value.message : String(value)))
  }, [])
  const rows: [string, string][] = [
    ['应用版本', about?.app_version || window.__APP_VERSION__ || '未知'],
    ['App ID', about?.app_id || 'com.ictrek.v-voice'],
    ['运行 Profile', about?.profile || '未知'],
    ['推理 Provider', about?.provider || '未知'],
    ['服务端口', about ? String(about.port) : '未知'],
    ['支持模型族', about ? `ASR ${about.supported_asr_families} 族 · TTS ${about.supported_tts_families} 族` : '未知'],
    ['并发配置', about ? `常驻模型 ${about.max_loaded_models} · 全局并发 ${about.max_concurrent_inference} · 单模型并发 ${about.max_concurrent_per_model}` : '未知'],
  ]
  return <Localized><div className="modal-overlay" role="dialog" aria-modal="true" aria-label="关于 V-Voice" onClick={onClose}>
    <div className="modal" onClick={event => event.stopPropagation()}>
      <div className="modal-head"><div><strong>关于 V-Voice</strong><span>ONNX voice runtime</span></div><button className="modal-close" onClick={onClose} aria-label="关闭">✕</button></div>
      {error ? <div className="alert" data-i18n="off">{error}</div> : null}
      <dl className="about-grid">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <p className="about-note">版本号由 VOS 安装包通过 <code>APP_VERSION</code> 环境变量注入（<code>runtime-config.js</code>），与 <code>/api/v1/about</code> 返回值一致。</p>
    </div>
  </div></Localized>
}

function Models({ models, loading, refresh }: { models: Model[]; loading: boolean; refresh: () => void }) {
  const [kind, setKind] = useState<'all' | 'asr' | 'tts' | 'speaker'>(() => {
    const value = new URLSearchParams(window.location.search).get('kind')
    return value === 'asr' || value === 'tts' || value === 'speaker' ? value : 'all'
  })
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const filtered = useMemo(() => kind === 'all' ? models : models.filter(model => model.kind === kind), [kind, models])
  const counts = useMemo(() => ({ all: models.length, asr: models.filter(model => model.kind === 'asr').length, tts: models.filter(model => model.kind === 'tts').length, speaker: models.filter(model => model.kind === 'speaker').length, ready: models.filter(model => model.status === 'ready').length }), [models])

  async function act(model: Model, action: 'pull' | 'force' | 'stop' | 'unload') {
    setBusy(`${model.key}:${action}`); setError('')
    try {
      if (action === 'pull') await api.pull(model.key)
      if (action === 'force') await api.pull(model.key, true)
      if (action === 'stop') await api.stop(model.key)
      if (action === 'unload') await api.unload(model.key)
      refresh()
    } catch (value) { setError(value instanceof Error ? value.message : String(value)) } finally { setBusy('') }
  }

  return <Localized><>
    <section className="section-heading"><div><p className="eyebrow">MODEL HUB</p><h1>模型管理</h1><p>{window.__VVOICE_GATEWAY__ ? '显示 V-Scheduler 已接入的语音模型服务，本地不加载模型。' : '显示公共 ONNX / GGUF 模型与校验状态，仅就绪模型对 V-Router 公开。'}</p></div><button className="secondary-button" onClick={refresh}>刷新状态</button></section>
    <section className="summary-strip" aria-label="模型统计"><div><strong>{counts.all}</strong><span>支持模型</span></div><div><strong>{counts.asr}</strong><span>ASR</span></div><div><strong>{counts.tts}</strong><span>TTS</span></div><div><strong>{counts.speaker}</strong><span>声纹</span></div><div><strong>{counts.ready}</strong><span>{window.__VVOICE_GATEWAY__ ? '可调用' : '已安装'}</span></div></section>
    <div className="catalog-tabs" role="tablist" aria-label="模型类型">{([['all', '全部模型', counts.all], ['asr', '语音识别 ASR', counts.asr], ['tts', '语音合成 TTS', counts.tts], ['speaker', '声纹识别', counts.speaker]] as const).map(([value, label, count]) => <button role="tab" aria-selected={kind === value} className={kind === value ? 'active' : ''} onClick={() => setKind(value)} key={value}><span>{label}</span><b>{count}</b></button>)}</div>
    {error ? <div className="alert" data-i18n="off">{error}</div> : null}
    {loading ? <div className="loading-card">正在读取模型目录…</div> : null}
    {!loading && !filtered.length ? <div className="loading-card">{window.__VVOICE_GATEWAY__ ? 'V-Scheduler 未提供此分类的模型服务。' : '该分类暂无模型。'}</div> : null}
    <div className="model-grid">{filtered.map(model => {
      const progress = Math.round((model.progress || 0) * 100)
      const voiceCount = Object.keys(model.voices || {}).length
      return <article className={`model-card ${model.status === 'ready' ? 'is-ready' : ''}`} key={model.key}>
        <div className="model-top"><span className={`kind ${model.kind}`}>{model.kind === 'asr' ? '语音识别' : model.kind === 'speaker' ? '声纹识别' : '语音合成'}</span>{model.streaming ? <span className="streaming-badge">流式</span> : null}<span className={`status ${model.status}`}><i />{statusNames[model.status] || model.status}</span></div>
        <div className="model-title"><div><h2 data-i18n="off">{model.name}</h2><code>{model.key}</code></div>{model.preferred ? <span className="recommended">推荐</span> : null}</div>
        <p className="description" data-i18n="off">{model.description}</p>
        <dl className="model-details"><div><dt>推理后端</dt><dd>{model.backend || 'sherpa-onnx'}{model.streaming ? ' · Online' : ''}</dd></div><div><dt>运行时</dt><dd>{model.backend === 'gateway' ? '由平台服务管理' : model.loaded ? '已热加载' : '按请求热加载'}</dd></div><div><dt>模型族</dt><dd>{model.family}</dd></div><div><dt>{model.kind === 'tts' ? 'Voice' : '接口'}</dt><dd>{model.kind === 'tts' ? `${voiceCount} 个预设音色` : model.kind === 'speaker' ? '注册 / 识别 / 验证' : `${model.translation === false ? '转写' : '转写 / 翻译'}${model.hotwords?.supported ? ' / 热词增强' : ''}${model.streaming ? ' / 实时流式' : ''}`}</dd></div><div className="wide"><dt>语言</dt><dd>{model.languages.map(language => languageNames[language] || language).join('、')}</dd></div>{model.backend !== 'gateway' ? <div className="wide"><dt>ModelScope</dt><dd><a href={`https://modelscope.cn/models/${model.modelscope_repo}`} target="_blank" rel="noreferrer">{model.modelscope_repo}</a></dd></div> : null}</dl>
        {model.status === 'downloading' ? <div className="progress"><i style={{ width: `${progress}%` }} /><small>{progress}% · {formatBytes(model.downloaded_bytes)} / {formatBytes(model.total_bytes)}</small></div> : null}
        {model.error ? <small className="error" data-i18n="off">{model.error}</small> : null}
        <div className="actions">
          {model.import_required ? <small>{model.backend === 'gateway' ? '请在 V-Scheduler 管理此模型服务' : '需管理员在 V-Scheduler 提供原始权重'}</small> : null}
          {model.status === 'ready' && model.backend !== 'gateway' ? <><button onClick={() => act(model, 'unload')} disabled={!!busy || !model.loaded}>卸载推理实例</button>{!model.import_required ? <button onClick={() => act(model, 'force')} disabled={!!busy}>重新下载</button> : null}</> : null}
          {model.status === 'downloading' ? <button onClick={() => act(model, 'stop')} disabled={!!busy}>停止下载</button> : null}
          {!model.import_required && model.status !== 'ready' && model.status !== 'downloading' ? <button className="primary" onClick={() => act(model, 'pull')} disabled={!!busy || model.status === 'verifying'}>从 V-Scheduler 安装</button> : null}
        </div>
      </article>
    })}</div>
  </></Localized>
}

function HotwordSets({ sets, refresh }: { sets: HotwordSet[]; refresh: () => void }) {
  const [name, setName] = useState(''); const [phrasesText, setPhrasesText] = useState('')
  const [importName, setImportName] = useState(''); const [importFile, setImportFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const [editing, setEditing] = useState<{ id: string; name: string; phrases: string } | null>(null)

  async function run(action: () => Promise<unknown>, done?: () => void) {
    setBusy(true); setError('')
    try { await action(); done?.(); refresh() } catch (value) { setError(value instanceof Error ? value.message : String(value)) } finally { setBusy(false) }
  }
  function create(event: FormEvent) {
    event.preventDefault()
    if (!name.trim() || !phrasesText.trim()) return
    void run(() => api.createHotwordSet(name.trim(), phrasesText.split(/[\n,]+/).map(item => item.trim()).filter(Boolean)), () => { setName(''); setPhrasesText('') })
  }
  function importSet(event: FormEvent) {
    event.preventDefault()
    if (!importName.trim() || !importFile) return
    void run(() => api.importHotwordSet(importName.trim(), importFile), () => { setImportName(''); setImportFile(null) })
  }
  return <Localized><section className="hotword-manager">
    <section className="section-heading"><div><p className="eyebrow">HOTWORDS</p><h1>热词管理</h1><p>保存常用热词集并在识别请求中直接引用。保存或更新时，服务端会自动生成模型所需的格式（Qwen3-ASR 提示词表、Zipformer contextual biasing 表），识别时与一次性热词合并去重。</p></div><button className="secondary-button" onClick={refresh}>刷新</button></section>
    <div className="hotword-forms">
      <form onSubmit={create}><h2>新建热词集</h2><label>名称<input value={name} onChange={event => setName(event.target.value)} maxLength={64} placeholder="例如：公司术语表" /></label><label className="wide">热词<textarea value={phrasesText} onChange={event => setPhrasesText(event.target.value)} rows={4} placeholder="华为, 昇腾, V-Voice" /></label><small>逗号或换行分隔；每个热词集最多 64 个热词、合计 4096 UTF-8 bytes</small><button className="primary" disabled={busy || !name.trim() || !phrasesText.trim()}>保存热词集</button></form>
      <form onSubmit={importSet}><h2>上传热词表</h2><label>名称<input value={importName} onChange={event => setImportName(event.target.value)} maxLength={64} placeholder="例如：产品名词表" /></label><label className="wide">热词文件<input type="file" accept="text/plain,.txt,.csv" onChange={event => setImportFile(event.target.files?.[0] || null)} /></label><small>UTF-8 文本，每行一个热词；上传后服务端自动解析并转化为各模型格式</small><button className="primary" disabled={busy || !importName.trim() || !importFile}>上传并转化</button></form>
    </div>
    {error ? <div className="alert" data-i18n="off">{error}</div> : null}
    {!sets.length ? <div className="loading-card">还没有保存的热词集。先在上方新建或上传一个，之后可在“识别”页直接选用。</div> : null}
    <div className="hotword-grid">{sets.map(item => {
      const editingThis = editing?.id === item.id
      return <article className="hotword-card" key={item.id}>
        <div className="hotword-top"><div><h2 data-i18n="off">{item.name}</h2><code>{item.id} · {item.phrase_count} 个热词 · 更新于 {item.updated_at.slice(0, 10)}</code></div></div>
        {editingThis ? <div className="hotword-edit">
          <label>名称<input value={editing.name} onChange={event => setEditing({ ...editing, name: event.target.value })} maxLength={64} /></label>
          <label>热词（换行或逗号分隔）<textarea value={editing.phrases} onChange={event => setEditing({ ...editing, phrases: event.target.value })} rows={4} /></label>
          <div className="hotword-actions"><button className="primary" disabled={busy} onClick={() => void run(() => api.updateHotwordSet(item.id, { name: editing.name.trim(), phrases: editing.phrases.split(/[\n,]+/).map(word => word.trim()).filter(Boolean) }), () => setEditing(null))}>保存修改</button><button onClick={() => setEditing(null)}>取消</button></div>
        </div> : <>
          <div className="hotword-list">{item.phrases.map(phrase => <span className="hotword-chip" data-i18n="off" key={phrase}>{phrase}</span>)}</div>
          <dl className="hotword-formats">{item.formats.map(fmt => <div key={fmt.format}><dt>{fmt.format === 'qwen3' ? 'Qwen3-ASR' : fmt.format === 'zipformer' ? 'Zipformer' : '通用文本'}</dt><dd><a href={api.hotwordSetExportUrl(item.id, fmt.format)}>{fmt.file} · {formatBytes(fmt.bytes)}</a></dd></div>)}</dl>
          <div className="hotword-actions">
            <button disabled={busy} onClick={() => setEditing({ id: item.id, name: item.name, phrases: item.phrases.join('\n') })}>编辑</button>
            <button disabled={busy} onClick={() => void run(() => api.deleteHotwordSet(item.id))}>删除</button>
          </div>
        </>}
      </article>
    })}</div>
  </section></Localized>
}

function SpeakerConsole({ models }: { models: Model[] }) {
  const ready = useMemo(() => models.filter(model => model.kind === 'speaker' && model.status === 'ready'), [models])
  const [speakers, setSpeakers] = useState<EnrolledSpeaker[]>([])
  const [model, setModel] = useState('')
  const [enrollName, setEnrollName] = useState(''); const [enrollFile, setEnrollFile] = useState<File | null>(null)
  const [identifyFile, setIdentifyFile] = useState<File | null>(null); const [threshold, setThreshold] = useState(0.6)
  const [identifyResult, setIdentifyResult] = useState<IdentifyResult | null>(null)
  const [verifySpeakerId, setVerifySpeakerId] = useState(''); const [verifyFile, setVerifyFile] = useState<File | null>(null); const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null)
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  const selectedModel = ready.find(item => item.key === model) || ready[0]
  const refresh = useCallback(() => api.enrolledSpeakers().then(setSpeakers).catch(() => setSpeakers([])), [])
  useEffect(() => { refresh() }, [refresh])
  async function run(action: () => Promise<unknown>, done?: () => void) {
    setBusy(true); setError('')
    try { await action(); done?.(); refresh() } catch (value) { setError(value instanceof Error ? value.message : String(value)) } finally { setBusy(false) }
  }
  const thresholdInput = <label>相似度阈值<input type="number" min="0" max="1" step="0.05" value={threshold} onChange={event => setThreshold(Number(event.target.value))} /><small>余弦相似度；默认 0.6，越高越严格</small></label>
  return <Localized><section className="hotword-manager">
    <section className="section-heading"><div><p className="eyebrow">SPEAKER ID</p><h1>声纹识别</h1><p>先用说话人音频注册声纹，再对任意音频做归属识别或 1:1 验证。声纹库保存在应用存储 <code>data/speakers.json</code>，全部已注册声纹通过 <code>/v1/audio/speakers</code> 对 V-Router 以 public 能力开放。</p></div><button className="secondary-button" onClick={refresh}>刷新声纹库</button></section>
    {!ready.length ? <div className="loading-card">暂无已就绪的声纹模型。请先到“模型”页安装 3D-Speaker CAM++ zh-en。</div> : <>
    <div className="hotword-forms">
      <form onSubmit={event => { event.preventDefault(); if (!enrollName.trim() || !enrollFile || !selectedModel) return; void run(() => api.enrollSpeaker(enrollName.trim(), selectedModel.key, enrollFile), () => { setEnrollName(''); setEnrollFile(null) }) }}>
        <h2>注册声纹</h2>
        <label>声纹模型<select aria-label="声纹模型" value={selectedModel?.key || ''} onChange={event => setModel(event.target.value)}>{ready.map(item => <option value={item.key} key={item.key}>{item.name} · {item.key}</option>)}</select><small>{`${ready.length} 个已就绪声纹模型`}</small></label>
        <label>说话人名称<input value={enrollName} onChange={event => setEnrollName(event.target.value)} maxLength={64} placeholder="例如：张三" /></label>
        <label className="wide">注册音频<input type="file" accept="audio/*" onChange={event => setEnrollFile(event.target.files?.[0] || null)} /><small>建议 10 秒以上清晰单人语音；服务端提取声纹向量后不再保存音频</small></label>
        <button className="primary" disabled={busy || !enrollName.trim() || !enrollFile}>提取声纹并注册</button>
      </form>
      <form onSubmit={event => { event.preventDefault(); if (!identifyFile || !selectedModel) return; void run(async () => setIdentifyResult(await api.identifySpeaker(selectedModel.key, identifyFile, threshold))) }}>
        <h2>识别说话人（1:N 归属）</h2>
        <label className="wide">待识别音频<input type="file" accept="audio/*" onChange={event => setIdentifyFile(event.target.files?.[0] || null)} /><small>返回与全部已注册声纹的余弦相似度排名，最高分超过阈值即判定归属</small></label>
        {thresholdInput}
        <button className="primary" disabled={busy || !identifyFile}>开始识别</button>
      </form>
    </div>
    <form className="verify-form" onSubmit={event => { event.preventDefault(); if (!verifyFile || !verifySpeakerId || !selectedModel) return; void run(async () => setVerifyResult(await api.verifySpeaker(selectedModel.key, verifySpeakerId, verifyFile, threshold))) }}>
      <h2>验证说话人（1:1 比对）</h2>
      <label>已注册说话人<select aria-label="验证说话人" value={verifySpeakerId} onChange={event => setVerifySpeakerId(event.target.value)}><option value="">选择说话人</option>{speakers.map(item => <option value={item.id} key={item.id}>{item.name} · {item.id}</option>)}</select><small>{`${speakers.length} 个已注册声纹`}</small></label>
      <label>待验证音频<input type="file" accept="audio/*" onChange={event => setVerifyFile(event.target.files?.[0] || null)} /></label>
      <button className="primary" disabled={busy || !verifyFile || !verifySpeakerId}>开始验证</button>
    </form>
    {error ? <div className="alert" data-i18n="off">{error}</div> : null}
    {identifyResult ? <div className="speaker-result">
      <h3>识别结果{identifyResult.identified ? <span className="match-badge ok">归属：<RawText>{identifyResult.speaker?.name}</RawText></span> : <span className="match-badge no">无匹配说话人</span>}</h3>
      <div className="table-wrap"><table><thead><tr><th>排名</th><th>说话人</th><th>相似度</th></tr></thead><tbody>{identifyResult.ranked.map((row, index) => <tr key={row.id}><td>{index + 1}</td><td data-i18n="off">{row.name} · {row.id}</td><td>{row.score.toFixed(4)}{row.score >= identifyResult.threshold ? ' ✓' : ''}</td></tr>)}</tbody></table></div>
    </div> : null}
    {verifyResult ? <div className="speaker-result"><h3>验证结果{verifyResult.verified ? <span className="match-badge ok">通过 · 相似度 {verifyResult.score.toFixed(4)}</span> : <span className="match-badge no">未通过 · 相似度 {verifyResult.score.toFixed(4)}</span>}</h3><p>说话人 {verifyResult.speaker.name}，阈值 {verifyResult.threshold}。</p></div> : null}
    <h2 className="speaker-list-title">已注册声纹（{speakers.length}）</h2>
    {!speakers.length ? <div className="loading-card">声纹库为空，先在上方注册一个说话人。</div> : <div className="hotword-grid">{speakers.map(item => <article className="hotword-card" key={item.id}>
      <div className="hotword-top"><div><h2 data-i18n="off">{item.name}</h2><code>{item.id} · {item.dimension} 维 · 注册于 {item.created_at.slice(0, 10)}</code></div></div>
      <div className="hotword-actions"><button disabled={busy} onClick={() => void run(() => api.deleteSpeaker(item.id))}>删除声纹</button></div>
    </article>)}</div>}
    </>}
  </section></Localized>
}

function AsrPlayground({ models, sets }: { models: Model[]; sets: HotwordSet[] }) {
  const ready = useMemo(() => models.filter(model => model.kind === 'asr' && model.status === 'ready'), [models])
  const [model, setModel] = useState(''); const [file, setFile] = useState<File | null>(null); const [hotwords, setHotwords] = useState(''); const [hotwordsFile, setHotwordsFile] = useState<File | null>(null); const [hotwordsScore, setHotwordsScore] = useState(1.5); const [hotwordSetId, setHotwordSetId] = useState(''); const [result, setResult] = useState(''); const [busy, setBusy] = useState(false)
  const selectedModel = ready.find(item => item.key === model) || ready[0]
  const selected = selectedModel?.key || ''
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!file || !selected) return
    setBusy(true); setResult('')
    const form = new FormData(); form.append('file', file); form.append('model', selected); form.append('response_format', 'verbose_json')
    if (selectedModel?.hotwords?.supported) {
      if (hotwordSetId) form.append('hotwords_set', hotwordSetId)
      if (hotwords.trim()) form.append('hotwords', hotwords)
      if (hotwordsFile) form.append('hotwords_file', hotwordsFile)
      if ((hotwordSetId || hotwords.trim() || hotwordsFile) && selectedModel.hotwords.score) form.append('hotwords_score', String(hotwordsScore))
    }
    try { const body = await api.transcribe(form); setResult(body.text || JSON.stringify(body, null, 2)) } catch (error) { setResult(error instanceof Error ? error.message : String(error)) } finally { setBusy(false) }
  }
  return <Localized><section className="playground"><p className="eyebrow">SPEECH TO TEXT</p><h1>语音识别</h1><p className="intro">上传音频并从已安装模型中选择。模型 key 不接受自由输入。</p>{!ready.length ? <EmptyReady kind="ASR" /> : <form onSubmit={submit}><label>模型<select aria-label="ASR 模型" value={selected} onChange={event => setModel(event.target.value)}>{ready.map(item => <option value={item.key} key={item.key}>{item.name} · {item.key}</option>)}</select><small>{ready.length} 个已就绪模型</small></label><label>音频文件<input type="file" accept="audio/*" onChange={event => setFile(event.target.files?.[0] || null)} /><small>WAV、MP3、FLAC、M4A 等常见格式</small></label>{selectedModel?.streaming ? <div className="field-note wide"><strong>该模型支持实时流式识别</strong><span>除整句上传外，可通过 <code>POST /v1/audio/streaming/transcriptions</code>（HTTP 分块）或 <code>/v1/audio/streaming/ws</code>（WebSocket 增量返回）边传边识别，详见 API 页“流式识别”章节。</span></div> : null}{selectedModel?.hotwords?.supported ? <><label>固化热词集<select aria-label="热词集" value={hotwordSetId} onChange={event => setHotwordSetId(event.target.value)}><option value="">不使用</option>{sets.map(item => <option value={item.id} key={item.id}>{item.name} · {item.phrase_count} 个热词</option>)}</select><small>{sets.length ? `与一次性热词合并去重，共 ${sets.length} 个已保存热词集` : '暂无已保存热词集，可到“热词”页创建'}</small></label><label>一次性热词<textarea value={hotwords} onChange={event => setHotwords(event.target.value)} rows={3} placeholder="华为, 昇腾, V-Voice" /><small>逗号或换行分隔，仅本次请求生效，与热词集/文件合并去重</small></label><label>热词文件<input type="file" accept="text/plain,.txt" onChange={event => setHotwordsFile(event.target.files?.[0] || null)} /><small>UTF-8 文本，每行一个热词，仅本次请求生效</small></label>{selectedModel.hotwords.score ? <label>增强分数<input type="number" min="0" max="10" step="0.1" value={hotwordsScore} onChange={event => setHotwordsScore(Number(event.target.value))} /><small>Zipformer 默认 {selectedModel.hotwords.default_score ?? 1.5}</small></label> : <div className="field-note"><strong>{selectedModel.family === 'SeACo-Paraformer' ? 'SeACo 神经热词' : 'Qwen3-ASR 提示词热词'}</strong><span>{selectedModel.family === 'SeACo-Paraformer' ? '每条热词最多 10 字符，无需设置增强分数。' : '该模型无需设置增强分数。'}</span></div>}</> : <div className="field-note wide"><strong>该模型不支持热词</strong><span>如需热词增强，请选择 SeACo、Qwen3-ASR 或 Zipformer。</span></div>}<button className="primary" disabled={!file || !selected || busy}>{busy ? '识别中…' : '开始识别'}</button></form>}<output>{result ? <RawText>{result}</RawText> : '识别结果会显示在这里。'}</output></section></Localized>
}

function TtsPlayground({ models }: { models: Model[] }) {
  const ready = useMemo(() => models.filter(model => model.kind === 'tts' && model.status === 'ready'), [models])
  const [model, setModel] = useState(''); const [text, setText] = useState('你好，欢迎使用 V-Voice。'); const [voice, setVoice] = useState(''); const [source, setSource] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const selectedModel = ready.find(item => item.key === model) || ready[0]
  const voices = Object.entries(selectedModel?.voices || {})
  const selectedVoice = voices.some(([key]) => key === voice) ? voice : voices[0]?.[0] || ''
  function selectModel(key: string) { const next = ready.find(item => item.key === key); setModel(key); setVoice(Object.keys(next?.voices || {})[0] || '') }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!selectedModel || !selectedVoice) return
    setBusy(true); setError('')
    try { const blob = await api.speech({ model: selectedModel.key, input: text, voice: selectedVoice, response_format: 'mp3' }); if (source) URL.revokeObjectURL(source); setSource(URL.createObjectURL(blob)) } catch (value) { setError(value instanceof Error ? value.message : String(value)) } finally { setBusy(false) }
  }
  const downloadName = `vvoice-${selectedModel?.key || 'tts'}-${selectedVoice || 'voice'}.mp3`
  return <Localized><section className="playground"><p className="eyebrow">TEXT TO SPEECH</p><h1>语音合成</h1><p className="intro">模型和 Voice 均来自当前目录，切换模型后自动更新可用音色。</p>{!ready.length ? <EmptyReady kind="TTS" /> : <form onSubmit={submit}><label>模型<select aria-label="TTS 模型" value={selectedModel?.key || ''} onChange={event => selectModel(event.target.value)}>{ready.map(item => <option value={item.key} key={item.key}>{item.name} · {item.key}</option>)}</select><small>{ready.length} 个已就绪模型</small></label><label>Voice<select aria-label="Voice" value={selectedVoice} onChange={event => setVoice(event.target.value)}>{voices.map(([key, value]) => <option value={key} key={key}>{key} · {languageNames[value.language] || value.language} · SID {value.sid}</option>)}</select><small>{voices.length} 个可用音色</small></label><label className="wide">文本<textarea value={text} onChange={event => setText(event.target.value)} rows={6} maxLength={20000} /><small>{`${text.length} / 20000 字符`}</small></label><button className="primary" disabled={!selectedModel || !selectedVoice || !text.trim() || busy}>{busy ? '合成中…' : '生成语音'}</button></form>}{error ? <div className="alert" data-i18n="off">{error}</div> : null}{source ? <div className="audio-result"><audio src={source} controls autoPlay /><a className="download-button" href={source} download={downloadName}>下载音频 · {downloadName}</a></div> : null}</section></Localized>
}

function CodeBlock({ children }: { children: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() { await navigator.clipboard.writeText(children); setCopied(true); window.setTimeout(() => setCopied(false), 1500) }
  return <Localized><div className="code-block"><button onClick={copy}>{copied ? '已复制' : '复制'}</button><pre>{children}</pre></div></Localized>
}

function ParameterTable({ rows }: { rows: [string, string, string, ReactNode][] }) {
  return <Localized><div className="table-wrap"><table><thead><tr><th>参数</th><th>类型</th><th>必填/默认</th><th>说明</th></tr></thead><tbody>{rows.map(([name, type, requirement, description]) => <tr key={name}><td><code>{name}</code></td><td>{type}</td><td>{requirement}</td><td>{description}</td></tr>)}</tbody></table></div></Localized>
}

function Endpoint({ method, path, title, children }: { method: 'GET' | 'POST' | 'PATCH' | 'DELETE'; path: string; title: string; children?: ReactNode }) {
  return <Localized><section className="endpoint"><div className="endpoint-title"><span className={method.toLowerCase()}>{method}</span><code>{path}</code><strong>{title}</strong></div>{children}</section></Localized>
}

const host = 'http://<VOS-IP>:22700'
const asrCurl = ["curl 'http://<VOS-IP>:22700/v1/audio/transcriptions' \\", "  -F 'file=@sample.wav' \\", "  -F 'model=qwen3-asr-0.6b' \\", "  -F 'language=zh' \\", "  -F 'hotwords_set=hw_1a2b3c4d' \\", "  -F 'hotwords=华为,昇腾,V-Voice' \\", "  -F 'speaker_model=speaker-campplus-zh-en' \\", "  -F 'timestamp_granularities[]=word' \\", "  -F 'timestamp_granularities[]=segment' \\", "  -F 'response_format=verbose_json'"].join('\n')
const ttsCurl = ["curl 'http://<VOS-IP>:22700/v1/audio/speech' \\", "  -H 'Content-Type: application/json' \\", "  -d '{\"model\":\"kokoro-multilang\",\"voice\":\"zf_xiaoxiao\",\"input\":\"你好\",\"response_format\":\"mp3\",\"speed\":1.0,\"language\":\"zh\"}' \\", '  --output speech.mp3'].join('\n')

function ApiGuide({ models }: { models: Model[] }) {
  const [tab, setTab] = useState<ApiTab>('overview')
  const tabs: [ApiTab, string][] = [['overview', '概览'], ['asr', '语音识别'], ['streaming', '流式识别'], ['tts', '语音合成'], ['creative', '创作语音与调度'], ['workbench', '音乐、编曲与任务'], ['hotwords', '热词管理'], ['speaker', '声纹识别'], ['models', '模型与发现']]
  return <Localized><section className="api-guide"><p className="eyebrow">OPENAI COMPATIBLE</p><h1>API 接入</h1><p className="intro">公共推理 API 不区分应用用户；创作项目和参考音色通过 VOS 身份隔离。经 V-Router 调用时使用其用户鉴权与模型权限。</p>
    <p><a href="../openapi.json" target="_blank" rel="noreferrer">OpenAPI JSON</a></p>
    <div className="api-addresses"><div><span>宿主机 / 局域网</span><code>{host}/v1</code></div><div><span>VOS 容器网络</span><code>http://v-voice-backend:7070/v1</code></div><div><span>鉴权</span><code>无需 API Key</code></div></div>
    <div className="api-tabs" role="tablist" aria-label="API 文档章节">{tabs.map(([value, label]) => <button role="tab" aria-selected={tab === value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)} key={value}>{label}</button>)}</div>
    {tab === 'workbench' ? <section className="api-section">
      <h2>音乐、编曲与任务</h2>
      <p>以下是现有工作台 RPC，不是 OpenAI 标准音乐接口；不会作为公共语音接口经网关转发。所有请求使用当前用户的 VOS Bearer Token，数据与结果按用户隔离。</p>
      <Endpoint method="POST" path="/studio-api/call" title="工作台调用契约">
        <ParameterTable rows={[
          ['method', 'string', '必填', '工作台方法名，见下面示例。'],
          ['data', 'object', '必填', '作品或方法参数，不接受服务器文件路径。'],
          ['requestId', 'string', '必填', '32 位十六进制稳定请求 ID；同一生成重试复用 ID 与相同参数，冲突会报错。'],
        ]} />
        <p>响应为 result 或 error；HTTP 200 也必须检查 error。生成返回任务 ID，不表示音频已完成。</p>
      </Endpoint>
      <Endpoint method="POST" path="/studio-api/call" title="音乐生成">
        <p>modelId 使用创作目录中的裸 ID，不带 audiocpp- 或 v-voice/。ACE-Step 支持纯音乐；YuE2 要求非空歌词，不支持纯音乐。</p>
        <CodeBlock>{JSON.stringify({ method: 'generation.start', requestId: '0123456789abcdef0123456789abcdef', data: { id: '1123456789abcdef0123456789abcdef', kind: 'music', title: 'Instrumental demo', modelId: 'ace-step-1.5-turbo-q8', text: 'Soft piano, calm ambient', instrumental: true, lyrics: '', synthesisLanguage: 'unknown', seed: 42 } }, null, 2)}</CodeBlock>
      </Endpoint>
      <Endpoint method="POST" path="/studio-api/call" title="编曲渲染">
        <p>modelId 选择 soundfont 家族的已就绪音色库。乐谱包含速度、拍号、声部和音符；音高与力度使用 MIDI 数值，小节和拍从 1 开始。</p>
        <CodeBlock>{JSON.stringify({ method: 'generation.start', requestId: '2123456789abcdef0123456789abcdef', data: { id: '3123456789abcdef0123456789abcdef', kind: 'score', title: 'Score demo', modelId: '<soundfont-id>', score: { tempo: 120, timeSignature: [4, 4], tracks: [{ id: 'piano', name: 'Piano', program: 0, notes: [{ bar: 1, beat: 1, pitch: 60, length: 1, velocity: 90 }] }] } } }, null, 2)}</CodeBlock>
      </Endpoint>
      <Endpoint method="POST" path="/studio-api/call" title="任务查询与取消">
        <p>使用 state.get 轮询 result.state.activity 与 history。operation.cancel 取消当前用户的任务；不要直接调用内部执行器。只有调度器确认成功后，结果才出现在历史中。</p>
        <CodeBlock>{JSON.stringify({ method: 'state.get', data: {}, requestId: '4123456789abcdef0123456789abcdef' }, null, 2) + '\n\n' + JSON.stringify({ method: 'operation.cancel', data: {}, requestId: '5123456789abcdef0123456789abcdef' }, null, 2)}</CodeBlock>
      </Endpoint>
      <Endpoint method="GET" path="/studio-api/media/outputs/{fileName}" title="结果与参考音色">
        <p>{'从当前用户的 history 读取 fileName，再以相同 VOS 身份下载。参考音色通过 /studio-api/media/voices/{fileName} 读取；其他用户或未获准的结果返回 404。'}</p>
      </Endpoint>
      <Endpoint method="GET" path="/api/v1/creative-models" title="创作模型目录">
        <p>此目录包含音乐、语音及音色库的全部精度和共享文件校验状态。下载和停止使用管理员 RPC model.download 与 model.cancel，data 为所选模型的 id；仅导入模型必须先由管理员提供权重。</p>
      </Endpoint>
    </section> : null}
    {tab === 'creative' ? <section className="api-section">
      <h2>创作语音与调度</h2>
      <p>新增创作语音扩展不是 OpenAI 标准参数；只有模型声明相应能力时才能使用。</p>
      <Endpoint method="POST" path="/v1/audio/speech" title="声音克隆、设计与情绪控制">
        <ParameterTable rows={[
          ['reference_audio', 'string', '可选', '参考音频的 Base64 编码，不接受服务器路径。'],
          ['reference_text', 'string', '可选', '参考音频的准确原文；OmniVoice 与 Breeze 克隆必填。'],
          ['voice_description', 'string', '可选', '声音设计或演绎指导；须匹配 voice_design 或 voice_instruction。'],
          ['emotion_text', 'string', '可选', '情绪描述，仅适用于声明 emotion_control 的 IndexTTS 模型。'],
          ['emotion_strength', 'number', '0–1', 'IndexTTS 情绪强度。'],
        ]} />
        <CodeBlock>{`curl '${host}/v1/audio/speech' -H 'Content-Type: application/json' -d '{"model":"audiocpp-kokoro-82m-q8","input":"Hello, V-Voice.","voice":"af_heart","response_format":"wav"}' -o speech.wav`}</CodeBlock>
        <p>Kokoro 使用内置音色，不支持克隆；Qwen3 Base、CustomVoice 和 VoiceDesign 的能力不同，请以发现接口为准。</p>
      </Endpoint>
      <h2>V-Router 与 V-Scheduler</h2>
      <p>V-Router 自动发现已就绪模型；经网关调用时使用带 v-voice/ 前缀的模型 ID，其余参数保持不变。</p>
      <p>直接调用和网关调用都必须通过 V-Scheduler 准入。新增模型须先配置批准的资源模板；许可交接不会重复预约资源，请勿自行设置内部许可头。</p>
      <p>创作工作台的 /studio-api/* 是用户私有业务接口，不属于 OpenAI 标准，也不会经 V-Router 暴露。异步任务只有在 Scheduler 确认成功后才交付结果。</p>
    </section> : null}
    {tab === 'overview' ? <div className="runtime-note"><strong>热加载与并发</strong><p>模型在首次推理时热加载，随后进入进程内 LRU 缓存；默认最多常驻 2 个推理实例，可在模型页手动卸载。请求进入全局和单模型两级队列，默认全局 2 路、每模型 key 2 路，超出后排队。可通过安装配置中的 <code>VVOICE_MAX_LOADED_MODELS</code>、<code>VVOICE_MAX_CONCURRENT_INFERENCE</code>、<code>VVOICE_MAX_CONCURRENT_PER_MODEL</code> 调整。超过 30 秒的长音频（<code>VVOICE_VAD_SPLIT_SECONDS</code>）会自动做 VAD 分段解码再按时间戳合并，避免整段解码劣化；流式模型原生分块不受影响。</p></div> : null}
    {tab === 'overview' ? <div className="api-section"><h2>端点一览</h2><div className="table-wrap"><table><thead><tr><th>方法</th><th>路径</th><th>用途</th><th>内容类型</th></tr></thead><tbody>{[['POST', '/v1/audio/transcriptions', '音频转写', 'multipart/form-data'], ['POST', '/v1/audio/streaming/transcriptions', '流式转写（chunked 实时解码）', 'chunked binary'], ['POST', '/v1/audio/streaming/ws', 'WebSocket 实时识别', 'websocket'], ['POST', '/v1/audio/translations', '音频翻译为英文', 'multipart/form-data'], ['POST', '/v1/audio/speech', '文本转语音', 'application/json'], ['GET', '/v1/audio/voices?model=...', '列出模型音色', 'application/json'], ['GET', '/v1/audio/speakers?model=...', '已注册声纹列表', 'application/json'], ['POST', '/v1/audio/speakers/identify', '声纹 1:N 归属', 'multipart/form-data'], ['POST', '/v1/audio/speakers/verify', '声纹 1:1 验证', 'multipart/form-data'], ['GET', '/v1/models', 'OpenAI 模型列表', 'application/json'], ['GET', '/api/v1/models', '完整目录与安装状态', 'application/json'], ['GET/POST/PATCH/DELETE', '/api/v1/hotwords', '热词集增删改查', 'application/json / multipart'], ['POST/DELETE', '/api/v1/speakers', '声纹注册 / 删除（管理面）', 'multipart / json'], ['GET', '/api/v1/creative-models', '完整创作模型状态（含音乐与音色库）', 'application/json'], ['GET', '/api/v1/scheduler/binding', '自动调度接入状态（不含凭据）', 'application/json'], ['POST', '/api/v1/scheduler/binding', '仅 V-Scheduler 应用身份可更新自动授权', 'application/json'], ['GET', '/api/v1/discovery', 'V-Router 服务发现', 'application/json'], ['GET', '/health', '存活与推理 Provider', 'application/json']].map(row => <tr key={row[1]}><td><b className={`method ${row[0].toLowerCase()}`}>{row[0]}</b></td><td><code>{row[1]}</code></td><td>{row[2]}</td><td>{row[3]}</td></tr>)}</tbody></table></div><div className="runtime-note"><strong>能力发现与 public 注册</strong><p>全部已就绪模型（ASR 整句 / ASR 流式 / TTS / 声纹）都会出现在 <code>/api/v1/discovery</code>，服务固定 <code>visibility=public</code>、<code>authentication=none</code>，V-Router 应将其全部作为 public 公共能力注册：按 <code>kind</code> 与 <code>capabilities</code> 区分能力（如 <code>streaming</code>、<code>hotwords</code>、<code>speaker-identification</code>），并按 <code>endpoints</code> 完整代理对应接口。接入要求详见本页各章节与 docs/v-router-discovery.md。</p></div><h2>错误处理</h2><ul className="error-list"><li><code>404</code> 模型 key、热词集或声纹 id 不存在，请以模型目录为准。</li><li><code>409</code> 模型尚未安装或文件未就绪，请先在模型页安装。</li><li><code>413</code> 上传音频超过服务限制。</li><li><code>422</code> 参数、Voice、热词内容或模型能力不匹配（例如对非流式模型调用流式接口）。</li><li><code>500</code> 推理失败；响应 <code>detail</code> 包含原因。</li></ul></div> : null}
    {tab === 'asr' ? <div className="api-section"><Endpoint method="POST" path="/v1/audio/transcriptions" title="音频转写"><ParameterTable rows={[["file", "binary", "必填", "待识别音频文件"], ["model", "string", "必填", "已就绪 ASR 模型 key"], ["language", "string", "空 / 自动", "语言代码，例如 zh、en"], ["response_format", "string", "json", "json、verbose_json、text、srt、vtt"], ["hotwords", "string", "空", "一次性热词，逗号或换行分隔；SeACo、Qwen3-ASR、Zipformer 支持"], ["hotwords_set", "string，可重复", "空", "已保存热词集 id（/api/v1/hotwords），与一次性热词合并去重"], ["hotwords_file", "UTF-8 file", "空", "一次性热词文件，每行一个热词，与 hotwords 合并去重"], ["hotwords_score", "number", "1.5", "0–10；仅 Zipformer 支持"], ["timestamp_granularities[]", "string，可重复", "空", "word、segment；配合 verbose_json"], ["speaker_model", "string", "空", "可选声纹模型 key；提供时 verbose_json 附带 speaker 归属块（边转写边声纹）"], ["speaker_threshold", "number", "0.6", "0–1；speaker 块的余弦相似度阈值"]]} /><CodeBlock>{asrCurl}</CodeBlock><p>热词集与一次性热词、热词文件合并去重，最多 64 个、合计 4096 UTF-8 bytes。不支持热词的模型会忽略全部热词字段并继续转写，客户端可统一提交；verbose_json 的 <code>hotwords.sets</code> 返回实际应用的集合。</p><h3>verbose_json 响应字段</h3><p><code>text</code>、<code>language</code>、<code>duration</code>、<code>words[]</code>、<code>segments[]</code>，时间单位为秒；携带 <code>speaker_model</code> 时另附 <code>speaker</code> 块（<code>identified</code>、<code>speaker</code>、<code>score</code>、<code>threshold</code>、Top-5 <code>ranked[]</code>），一次上传同时得到文本与说话人归属。SenseVoice、Paraformer、Zipformer 有词时间戳；Qwen3-ASR、Whisper Tiny 返回空数组，不伪造。请先读取 discovery 的 capability。</p><p>SenseVoice 额外返回整句归属性标签：<code>lang</code>（检测语言，如 zh/en/yue）、<code>emotion</code>（情绪：HAPPY/SAD/ANGRY/NEUTRAL…）、<code>event</code>（音频事件：BGM/Applause/Laughter…，无事件为 N/A）。识别结果默认不附加声纹；传入 <code>speaker_model</code> 后可使用独立声纹模型返回说话人归属，未提供时不会伪造。</p><p><strong>流式识别说明</strong>：SeACo 与其他未声明 streaming 能力的模型使用整句接口，不提供增量解码；需要准实时效果时，可按 VAD 分段后循环调用整句接口。实时流式模型请参阅“流式识别”章节。</p></Endpoint><Endpoint method="POST" path="/v1/audio/translations" title="翻译为英文"><p>参数与 transcriptions 相同，包括热词集、热词文本、热词文件、增强分数和时间戳粒度；支持翻译任务的模型会返回英文文本。</p><CodeBlock>{["curl 'http://<VOS-IP>:22700/v1/audio/translations' \\", "  -F 'file=@sample.wav' -F 'model=whisper-tiny' -F 'response_format=json'"].join('\n')}</CodeBlock></Endpoint></div> : null}
    {tab === 'tts' ? <div className="api-section"><Endpoint method="POST" path="/v1/audio/speech" title="文本转语音"><ParameterTable rows={[["model", "string", "必填", "已就绪 TTS 模型 key"], ["input", "string", "必填", "1–20000 字符"], ["voice", "string", "default", "必须来自 voices 接口的 id"], ["response_format", "string", "mp3", "mp3、opus、aac、flac、wav、pcm"], ["speed", "number", "1.0", "0.25–4.0"], ["language", "string", "模型默认", "多语言模型可指定"]]} /><CodeBlock>{ttsCurl}</CodeBlock></Endpoint><Endpoint method="GET" path="/v1/audio/voices?model=kokoro-multilang" title="查询可用 Voice"><CodeBlock>{`curl '${host}/v1/audio/voices?model=kokoro-multilang'`}</CodeBlock><p>响应包含 <code>model</code>、<code>default_voice</code> 以及同值的 <code>voices[]</code>/<code>data[]</code>。每项至少有 <code>id</code>、<code>name</code>；模型变化时必须重新请求并重建下拉框，合成时提交所选 id，不能自由填写或沿用其他模型的 voice。</p></Endpoint></div> : null}
    {tab === 'streaming' ? <div className="api-section">
      <div className="runtime-note"><strong>流式识别（仅 streaming 模型）</strong><p>带 <code>streaming</code> capability 的模型（如 <code>zipformer-en-streaming</code>、<code>zipformer-zh-streaming</code>）由 sherpa-onnx <code>OnlineRecognizer</code> 驱动，支持边收音频边解码。其余模型为整句识别，调用流式接口会返回 422。流式请求会占用一个模型并发槽，长连接期间其他请求排队。</p></div>
      <Endpoint method="POST" path="/v1/audio/streaming/transcriptions" title="HTTP 分块流式转写"><ParameterTable rows={[["(body)", "binary chunked", "必填", "音频字节流；pcm 为 s16le 单声道，wav 为无压缩单声道 RIFF，auto 缓冲后整体解码"], ["model", "query string", "必填", "带 streaming capability 的模型 key"], ["format", "query string", "pcm", "pcm、wav、auto"], ["sample_rate", "query integer", "16000", "format=pcm 的采样率；wav 使用文件头"], ["hotwords", "query string", "空", "一次性热词，逗号分隔（流式 Zipformer 支持）"], ["hotwords_set", "query string，可重复", "空", "已保存热词集 id"], ["hotwords_score", "query number", "1.5", "0–10，仅流式 Zipformer"], ["response_format", "query string", "verbose_json", "verbose_json、json、text"], ["speaker_model", "query string", "空", "可选声纹模型 key；最终响应附 speaker 归属块"], ["speaker_threshold", "query number", "0.6", "0–1；speaker 块阈值"]]} /><CodeBlock>{["curl 'http://<VOS-IP>:22700/v1/audio/streaming/transcriptions?model=zipformer-zh-streaming&format=pcm&sample_rate=16000' \\", "  --header 'Transfer-Encoding: chunked' \\", "  --data-binary @audio.pcm"].join('\n')}</CodeBlock><p>请求体边到边解码，body 结束时返回最终转写；响应与 verbose_json 转写一致并附 <code>streaming: true</code>，携带 <code>speaker_model</code> 时附 <code>speaker</code> 归属块。V-Router 等代理必须透传 chunked 请求体且不缓冲整个请求。</p></Endpoint>
      <Endpoint method="POST" path="/v1/audio/streaming/ws" title="WebSocket 实时识别"><p>连接参数同上（<code>model</code>、<code>format=pcm|wav</code>、<code>sample_rate</code>、热词参数）。协议：客户端发<strong>二进制帧</strong>（s16le 单声道 PCM 分片）；服务端在识别推进时回 JSON <code>{'{"type":"partial","text":...,"is_endpoint":...}'}</code>；客户端发文本帧 <code>{'{"type":"finish"}'}</code> 或断开后，服务端返回 <code>{'{"type":"final","text":...,"tokens":[...],"timestamps":[...]}'}</code>（连接时带 <code>speaker_model</code> 则 final 附 <code>speaker</code> 归属块）并关闭。错误以 <code>{'{"type":"error","detail":...}'}</code> 返回并按 4404/4409/4422/4500 关闭。</p><CodeBlock>{['# Python (websockets)', 'async with websockets.connect(f"ws://<VOS-IP>:22700/v1/audio/streaming/ws?model=zipformer-en-streaming") as ws:', '    await ws.send(pcm_chunk)          # 100ms 一片', '    partial = json.loads(await ws.recv())', '    await ws.send(json.dumps({"type": "finish"}))', '    final = json.loads(await ws.recv())'].join('\n')}</CodeBlock></Endpoint></div> : null}
    {tab === 'speaker' ? <div className="api-section">
      <div className="runtime-note"><strong>声纹识别（public 能力）</strong><p>声纹模型（<code>kind=speaker</code>）通过余弦相似度做 1:N 归属与 1:1 验证。注册属管理面（<code>/api/v1/speakers</code>），识别/验证属公共推理面，V-Router 以 public 能力代理。建议注册与识别使用同一模型；默认阈值 0.6。</p></div>
      <Endpoint method="GET" path="/v1/audio/speakers?model=..." title="已注册声纹列表"><CodeBlock>{`curl '${host}/v1/audio/speakers?model=speaker-campplus-zh-en'`}</CodeBlock><p>返回 <code>speakers[]</code>/<code>data[]</code>（同值），每项含 <code>id</code>、<code>name</code>、<code>dimension</code>、<code>created_at</code>，并给出 <code>default_threshold</code>；不返回声纹向量。</p></Endpoint>
      <Endpoint method="POST" path="/v1/audio/speakers/identify" title="识别说话人（1:N）"><ParameterTable rows={[["file", "binary", "必填", "待归属音频"], ["model", "string", "speaker-campplus-zh-en", "已就绪声纹模型 key"], ["threshold", "number", "0.6", "0–1 余弦相似度阈值"]]} /><CodeBlock>{`curl -X POST '${host}/v1/audio/speakers/identify' -F model=speaker-campplus-zh-en -F threshold=0.6 -F file=@sample.wav`}</CodeBlock><p>响应：<code>identified</code>、命中的 <code>speaker</code>（<code>id</code>/<code>name</code>/<code>score</code>）、<code>threshold</code>，以及 Top-5 <code>ranked[]</code>。无人超过阈值时 <code>identified=false</code>、<code>speaker=null</code>。</p></Endpoint>
      <Endpoint method="POST" path="/v1/audio/speakers/verify" title="验证说话人（1:1）"><ParameterTable rows={[["file", "binary", "必填", "待验证音频"], ["speaker", "string", "必填", "已注册声纹 id 或名称"], ["model", "string", "speaker-campplus-zh-en", "已就绪声纹模型 key"], ["threshold", "number", "0.6", "0–1 余弦相似度阈值"]]} /><CodeBlock>{`curl -X POST '${host}/v1/audio/speakers/verify' -F speaker=sp_1a2b3c4d -F file=@sample.wav`}</CodeBlock><p>响应：<code>verified</code>、<code>score</code>、<code>threshold</code>、<code>speaker</code>。</p></Endpoint>
      <Endpoint method="POST" path="/api/v1/speakers" title="注册声纹（管理面）"><ParameterTable rows={[["name", "string", "必填", "说话人名称，1–64 字符"], ["file", "binary", "必填", "注册音频（建议 ≥10 秒单人语音）"], ["model", "string", "speaker-campplus-zh-en", "声纹模型 key"]]} /><CodeBlock>{`curl -X POST '${host}/api/v1/speakers' -F name=张三 -F model=speaker-campplus-zh-en -F file=@zhangsan.wav`}</CodeBlock></Endpoint><Endpoint method="DELETE" path="/api/v1/speakers/{id}" title="删除声纹（管理面）"><CodeBlock>{`curl -X DELETE '${host}/api/v1/speakers/sp_1a2b3c4d'`}</CodeBlock></Endpoint></div> : null}
    {tab === 'hotwords' ? <div className="api-section"><Endpoint method="GET" path="/api/v1/hotwords" title="查询热词集列表"><p>返回全部已保存热词集（增删改查的“查”）。每个集合包含 <code>id</code>、<code>name</code>、<code>phrases[]</code>、<code>phrase_count</code>、<code>updated_at</code> 以及服务端已转化的 <code>formats[]</code>（text / qwen3 / zipformer 三种格式及字节数）。</p><CodeBlock>{`curl '${host}/api/v1/hotwords'`}</CodeBlock></Endpoint><Endpoint method="POST" path="/api/v1/hotwords" title="新建热词集（增）"><ParameterTable rows={[["name", "string", "必填", "名称，1–64 字符"], ["phrases", "string[]", "至少一项", "热词数组，优先于 phrases_text"], ["phrases_text", "string", "空", "逗号/换行分隔的热词文本"]]} /><CodeBlock>{`curl -X POST '${host}/api/v1/hotwords' -H 'Content-Type: application/json' -d '{"name":"公司术语","phrases":["华为","昇腾"]}'`}</CodeBlock></Endpoint><Endpoint method="POST" path="/api/v1/hotwords/import" title="上传热词表"><p>multipart 上传 UTF-8 热词表（每行一个热词）。上传后服务端自动解析并后台转化为 Qwen3-ASR / Zipformer / 通用文本三种格式，供支持热词表的模型直接读取。</p><CodeBlock>{`curl -X POST '${host}/api/v1/hotwords/import' -F 'name=产品名词' -F 'file=@hotwords.txt'`}</CodeBlock></Endpoint><Endpoint method="PATCH" path="/api/v1/hotwords/{id}" title="修改热词集（改）"><ParameterTable rows={[["name", "string", "可选", "新名称"], ["phrases", "string[]", "可选", "新热词列表，整体替换"]]} /><CodeBlock>{`curl -X PATCH '${host}/api/v1/hotwords/hw_1a2b3c4d' -H 'Content-Type: application/json' -d '{"phrases":["V-Voice"]}'`}</CodeBlock></Endpoint><Endpoint method="DELETE" path="/api/v1/hotwords/{id}" title="删除热词集（删）"><CodeBlock>{`curl -X DELETE '${host}/api/v1/hotwords/hw_1a2b3c4d'`}</CodeBlock></Endpoint><Endpoint method="GET" path="/api/v1/hotwords/{id}/export?format=..." title="导出模型格式"><p><code>format</code> 可选 <code>text</code>（通用一行一个）、<code>qwen3</code>（逗号分隔提示词）、<code>zipformer</code>（contextual biasing 一行一个）。热词集在识别请求中通过 <code>POST /v1/audio/transcriptions</code> 的 <code>hotwords_set</code> 字段引用。</p><CodeBlock>{`curl '${host}/api/v1/hotwords/hw_1a2b3c4d/export?format=qwen3'`}</CodeBlock></Endpoint></div> : null}
    {tab === 'models' ? <div className="api-section"><Endpoint method="GET" path="/v1/models" title="OpenAI 兼容模型列表"><p>只返回当前已就绪模型，适合客户端和 V-Router 调用。</p><CodeBlock>{`curl '${host}/v1/models'`}</CodeBlock></Endpoint><Endpoint method="GET" path="/api/v1/models" title="模型管理目录"><p>返回全部 {models.length || 12} 个支持模型、Voice、安装状态与下载进度。</p><CodeBlock>{`curl '${host}/api/v1/models'`}</CodeBlock></Endpoint><Endpoint method="POST" path="/api/v1/models/{key}/pull" title="安装模型"><ParameterTable rows={[["key", "path string", "必填", "模型目录中的 key"], ["force", "query boolean", "false", "true 时强制重新下载"]]} /><CodeBlock>{`curl -X POST '${host}/api/v1/models/sensevoice-int8/pull?force=false'`}</CodeBlock></Endpoint><Endpoint method="GET" path="/api/v1/discovery" title="V-Router 主动发现"><p>公开返回服务标识、容器内 base URL、健康检查路径和所有已就绪模型。固定为 <code>visibility=public</code>、<code>multi_tenant=false</code>、<code>authentication=none</code>。</p><CodeBlock>{`curl '${host}/api/v1/discovery'`}</CodeBlock></Endpoint></div> : null}
  </section></Localized>
}

export function App() {
  const language = useLanguage()
  const [tab, setTab] = useState<Tab>(() => { const page = new URLSearchParams(window.location.search).get('page'); return (['models', 'asr', 'tts', 'hotwords', 'speaker', 'api'] as const).find(tab => tab === page) ?? 'models' }); const [models, setModels] = useState<Model[]>([]); const [sets, setSets] = useState<HotwordSet[]>([]); const [error, setError] = useState(''); const [loading, setLoading] = useState(true); const [aboutOpen, setAboutOpen] = useState(false)
  const refresh = useCallback(() => { setError(''); return api.models().then(setModels).catch(value => setError(value.message || String(value))).finally(() => setLoading(false)) }, [])
  const refreshSets = useCallback(() => { return api.hotwordSets().then(setSets).catch(() => setSets([])) }, [])
  const downloading = models.some(model => model.status === 'downloading')
  useEffect(() => { refresh() }, [refresh])
  useEffect(() => { refreshSets() }, [refreshSets])
  useEffect(() => { if (!downloading) return; const timer = window.setInterval(refresh, 3000); return () => window.clearInterval(timer) }, [downloading, refresh])
  return <Localized><div className="shell"><header>{window.location.pathname.includes("/app/") && new URLSearchParams(window.location.search).get("standalone") !== "1" ? <a href="../" className="secondary-button" data-testid="return-workbench">返回工作台</a> : null}<div className="brand"><img src="./icon.png" alt="" /><div><strong>V-Voice</strong><span>ONNX voice runtime</span></div></div><div className="header-side"><nav>{([['models', '模型'], ['asr', '识别'], ['tts', '合成'], ['hotwords', '热词'], ['speaker', '声纹'], ['api', 'API']] as [Tab, string][]).map(([value, label]) => <button className={tab === value ? 'active' : ''} onClick={() => setTab(value)} key={value}>{label}</button>)}</nav><select className="language-select" aria-label="界面语言" value={language.mode} onChange={event => setLanguageMode(event.target.value as LanguageMode)}><option value="auto">跟随 VOS</option><option value="zh-CN">简体中文</option><option value="zh-TW">繁體中文</option><option value="en-US">English</option></select><button className="about-button" onClick={() => setAboutOpen(true)} aria-label="关于 V-Voice">关于</button></div></header><main>{error ? <div className="alert global-alert"><strong>无法读取模型目录</strong><span data-i18n="off">{error}</span><button onClick={refresh}>重试</button></div> : null}{tab === 'models' ? <Models models={models} loading={loading} refresh={refresh} /> : null}{tab === 'asr' ? <AsrPlayground models={models} sets={sets} /> : null}{tab === 'tts' ? <TtsPlayground models={models} /> : null}{tab === 'hotwords' ? <HotwordSets sets={sets} refresh={refreshSets} /> : null}{tab === 'speaker' ? <SpeakerConsole models={models} /> : null}{tab === 'api' ? <ApiGuide models={models} /> : null}</main>{aboutOpen ? <AboutDialog onClose={() => setAboutOpen(false)} /> : null}</div></Localized>
}
