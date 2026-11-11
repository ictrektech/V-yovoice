/** Public catalogue facts; no audio, credentials or user files cross this endpoint. */
export interface AudioCatalog {
  /** Configured ASR model, empty before selection. */
  selected: string
  /** ASR identities and calibrated readiness from the configured service. */
  models: { key: string; name: string; ready: boolean }[]
}

/** Latest saved transcript that can be restored beside an audio player. */
export interface AudioSavedTranscript {
  /** Digest-derived source identity used by the tool. */
  source: string
  /** Exact uploaded attachment identity when the source came from the conversation. */
  attachmentId?: string
  /** Original display name. */
  file: string
  /** ASR model that produced the text. */
  model: string
  /** Complete persisted original text. */
  text: string
}
