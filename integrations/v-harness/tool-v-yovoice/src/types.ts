/** Public catalogue facts; no audio, credentials or user files cross this endpoint. */
export interface AudioCatalog {
  /** Configured ASR model, empty before selection. */
  selected: string
  /** ASR identities and calibrated readiness from the configured service. */
  models: { key: string; name: string; ready: boolean }[]
  /** Configured speech model, voices and readiness from the same service. */
  speech: SpeechCatalog
}

/** TTS identity advertised by the configured V-yovoice service. */
export interface SpeechModel {
  /** Service-owned model key. */
  key: string
  /** Human-readable model name. */
  name: string
  /** Whether the model files are ready for inference. */
  ready: boolean
  /** Model language codes. */
  languages: string[]
  /** Public speech capabilities such as voice_design and emotion_control. */
  capabilities: string[]
  /** Built-in voices associated with this model. */
  voices: SpeechVoice[]
}

/** One built-in voice accepted by a TTS model. */
export interface SpeechVoice {
  /** Machine-readable voice identity submitted to the service. */
  id: string
  /** Display name returned by the service. */
  name: string
  /** Optional language code. */
  language?: string
}

/** Speech configuration and model choices shown on the plugin page. */
export interface SpeechCatalog {
  /** Configured TTS model, empty before selection. */
  selectedModel: string
  /** Configured default voice, empty before selection. */
  selectedVoice: string
  /** TTS models advertised by the service. */
  models: SpeechModel[]
  /** Voices for the configured model. */
  voices: SpeechVoice[]
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

/** Generated speech restored into the owning turn after a session reload. */
export interface AudioSavedSpeech {
  /** Distinguishes generated speech from an uploaded audio source. */
  audioSpeech: true
  /** Durable attachment identity used by the authenticated playback route. */
  attachmentId: string
  /** User-visible WAV filename. */
  file: string
  /** TTS model that produced the audio. */
  model: string
  /** Built-in voice used for synthesis. */
  voice: string
  /** Exact text submitted to the service. */
  text: string
  /** Stored WAV bytes. */
  bytes: number
  /** Optional language requested for synthesis. */
  language?: string
}
