export type Voice = {
  sid: number
  language: string
}

export type Model = {
  key: string
  name: string
  kind: 'asr' | 'tts' | 'speaker'
  streaming?: boolean
  family: string
  backend?: string
  translation?: boolean
  modelscope_repo: string
  description: string
  languages: string[]
  voices?: Record<string, Voice>
  status: string
  progress?: number
  downloaded_bytes?: number
  total_bytes?: number
  error?: string
  preferred?: boolean
  loaded?: boolean
  hotwords?: {
    supported: boolean
    formats: ('text' | 'file')[]
    score: boolean
    default_score?: number
  }
  timestamps?: {
    word: boolean
    segment: boolean
    source: string
  }
}

export type EnrolledSpeaker = {
  id: string
  name: string
  created_at: string
  model: string
  dimension: number
}

export type IdentifyResult = {
  identified: boolean
  speaker: EnrolledSpeaker & { score?: number } | null
  score: number
  threshold: number
  ranked: { id: string; name: string; score: number }[]
}

export type VerifyResult = {
  verified: boolean
  score: number
  threshold: number
  speaker: EnrolledSpeaker
}

export type HotwordFormat = { format: string; file: string; bytes: number }

export type HotwordSet = {
  id: string
  name: string
  phrases: string[]
  phrase_count: number
  created_at: string
  updated_at: string
  formats: HotwordFormat[]
}

export type AboutInfo = {
  app_id: string
  app_version: string
  profile: string
  provider: string
  port: number
  supported_asr_families: number
  supported_tts_families: number
  max_loaded_models: number
  max_concurrent_inference: number
  max_concurrent_per_model: number
}

const APP_PATH = '/app/com.ictrek.v-voice'

export function resolveApiPath(path: string, pathname = window.location.pathname) {
  const prefix = pathname === APP_PATH || pathname.startsWith(`${APP_PATH}/`) ? APP_PATH : ''
  return `${prefix}/${path.replace(/^\/+/, '')}`
}

function readableError(response: Response, body: string) {
  try {
    const parsed = JSON.parse(body)
    return parsed.detail || parsed.message || `${response.status} ${response.statusText}`
  } catch {
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('text/html') || /<html[\s>]/i.test(body)) {
      return `服务请求失败（HTTP ${response.status}），请刷新页面或检查 V-Voice 服务状态。`
    }
    return body.trim() || `${response.status} ${response.statusText}`
  }
}

async function request(path: string, init?: RequestInit) {
  const response = await fetch(resolveApiPath(path), init)
  if (!response.ok) throw new Error(readableError(response, await response.text()))
  return response
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  return response.json()
}

export const api = {
  about: () => json<AboutInfo>('/api/v1/about'),
  models: () => json<Model[]>('/api/v1/models'),
  pull: (key: string, force = false) => json(`/api/v1/models/${encodeURIComponent(key)}/pull?force=${force}`, { method: 'POST' }),
  stop: (key: string) => json(`/api/v1/models/${encodeURIComponent(key)}/stop`, { method: 'POST' }),
  unload: (key: string) => json(`/api/v1/models/${encodeURIComponent(key)}/unload`, { method: 'POST' }),
  hotwordSets: () => json<HotwordSet[]>('/api/v1/hotwords'),
  createHotwordSet: (name: string, phrases: string[]) =>
    json<HotwordSet>('/api/v1/hotwords', { method: 'POST', body: JSON.stringify({ name, phrases }) }),
  importHotwordSet: (name: string, file: File) => {
    const form = new FormData()
    form.append('name', name)
    form.append('file', file)
    return json<HotwordSet>('/api/v1/hotwords/import', { method: 'POST', body: form })
  },
  updateHotwordSet: (id: string, payload: { name?: string; phrases?: string[] }) =>
    json<HotwordSet>(`/api/v1/hotwords/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteHotwordSet: (id: string) => json(`/api/v1/hotwords/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  hotwordSetExportUrl: (id: string, format: string) =>
    resolveApiPath(`/api/v1/hotwords/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}`),
  enrolledSpeakers: () => json<EnrolledSpeaker[]>('/api/v1/speakers'),
  enrollSpeaker: (name: string, model: string, file: File) => {
    const form = new FormData()
    form.append('name', name)
    form.append('model', model)
    form.append('file', file)
    return json<EnrolledSpeaker>('/api/v1/speakers', { method: 'POST', body: form })
  },
  deleteSpeaker: (id: string) => json(`/api/v1/speakers/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  identifySpeaker: (model: string, file: File, threshold = 0.6) => {
    const form = new FormData()
    form.append('model', model)
    form.append('threshold', String(threshold))
    form.append('file', file)
    return json<IdentifyResult>('/v1/audio/speakers/identify', { method: 'POST', body: form })
  },
  verifySpeaker: (model: string, speaker: string, file: File, threshold = 0.6) => {
    const form = new FormData()
    form.append('model', model)
    form.append('speaker', speaker)
    form.append('threshold', String(threshold))
    form.append('file', file)
    return json<VerifyResult>('/v1/audio/speakers/verify', { method: 'POST', body: form })
  },
  transcribe: async (form: FormData) => {
    const response = await request('/v1/audio/transcriptions', { method: 'POST', body: form })
    return response.json()
  },
  speech: async (payload: Record<string, unknown>) => {
    const response = await request('/v1/audio/speech', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return response.blob()
  },
}

export function formatBytes(value?: number) {
  if (!value) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`
}
