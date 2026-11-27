/// <reference types="vite/client" />

interface VoicePlacement {
  deployment_id: string
  executor_id: string
  node_id: string
  node_name?: string | null
  profile: string
  model_id: string
}

interface Window {
  __APP_VERSION__?: string
  vvoiceCompute?: {
    placements: (signal: AbortSignal) => Promise<Response>
    transcribe: (body: FormData, signal: AbortSignal) => Promise<Response>
    speech: (body: string, signal: AbortSignal) => Promise<Response>
    speaker: (action: 'enroll' | 'identify' | 'verify', body: FormData, signal: AbortSignal) => Promise<Response>
  }
}
