/** Stable references to user-visible V-yovoice results. */
import type { CapabilityId } from './capability.ts'

type Json = null | boolean | number | string | Json[] | { [key: string]: Json }

/** Provenance fields are JSON-safe because they are persisted as tool metadata. */
export interface ArtifactProvenance extends Record<string, Json> {
  capability: CapabilityId
  model?: string
}

/** One result that can be restored, played, copied or downloaded. */
export interface ArtifactRef extends Record<string, Json> {
  /** Stable identity within the owning conversation. */
  id: string
  /** User-visible result kind. */
  kind: 'audio' | 'transcript' | 'score' | 'midi' | 'stems'
  /** IANA media type. */
  mimeType: string
  /** Source digest or service-owned identity. */
  source: string
  /** Capability and model that produced the result. */
  provenance: ArtifactProvenance
}

/** Describe a verbatim transcript without putting its full text in the artifact identity. */
export function transcriptArtifact(input: {
  source: string
  model: string
  file: string
}): ArtifactRef {
  return {
    id: `transcript:${input.source}`,
    kind: 'transcript',
    mimeType: 'text/plain; charset=utf-8',
    source: input.source,
    provenance: {
      capability: 'transcription',
      model: input.model,
    },
  }
}
