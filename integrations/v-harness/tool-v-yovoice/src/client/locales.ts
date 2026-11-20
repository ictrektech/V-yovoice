/** Plugin-owned UI copy. */
export const NS = 'audioTranscription'
/** Simplified Chinese labels. */
export const zh = {
  title: 'V-yovoice', description: '使用 V-yovoice 转写会话音频或把文本生成语音。先保存服务地址，再检查连接并选择已就绪模型与默认音色。',
  baseUrl: '服务根地址', model: 'ASR 模型', speechModel: 'TTS 模型', speechVoice: '默认音色', requestTimeoutMs: '请求时限（毫秒）',
  maxUploadBytes: '上传上限（字节）', maxResponseBytes: '响应上限（字节）', pageCharacters: '模型每页字符数',
  maxSpeechBytes: '语音文件上限（字节）', chooseSpeechModel: '选择 TTS 模型', chooseSpeechVoice: '选择默认音色',
  check: '检查连接 / 获取模型', checking: '正在检查…', choose: '选择模型', ready: '已就绪', notReady: '未就绪',
  original: '音频转写原文', previousOriginal: '上一次成功原文', failed: '音频转写失败', empty: '未识别到语音内容', audio: '音频',
  running: '正在转写…', unavailable: '转写详情不可用', playbackUnavailable: '此音频无法在当前宿主播放；原文仍可查看。',
  playbackFailed: '浏览器无法播放此音频。', download: '下载原音频', copy: '复制原文', copied: '已复制',
  speech: '生成语音', speechGenerated: '语音已生成', speechGenerating: '正在生成语音…', speechFailed: '语音生成失败',
  speechText: '朗读文本', downloadSpeech: '下载语音', generatedSpeech: '生成语音',
  play: '播放', pause: '暂停', seek: '音频进度',
  save: '保存', saving: '保存中…', saveFailed: '保存失败，请检查配置。', readOnly: '当前配置只读。',
  configUnavailable: '配置当前不可用。', overridden: '已覆盖', reset: '恢复默认', invalid: '请输入有效值。',
} as const
/** Complete English counterpart. */
export const en: Record<keyof typeof zh, string> = {
  title: 'V-yovoice', description: 'Transcribe conversation audio or turn text into speech with V-yovoice. Save the service address, check the connection, then select ready models and a default voice.',
  baseUrl: 'Service root URL', model: 'ASR model', speechModel: 'TTS model', speechVoice: 'Default voice', requestTimeoutMs: 'Request deadline (ms)',
  maxUploadBytes: 'Upload cap (bytes)', maxResponseBytes: 'Response cap (bytes)', pageCharacters: 'Characters per model page',
  maxSpeechBytes: 'Speech file cap (bytes)', chooseSpeechModel: 'Select a TTS model', chooseSpeechVoice: 'Select a default voice',
  check: 'Check connection / list models', checking: 'Checking…', choose: 'Select a model', ready: 'Ready', notReady: 'Not ready',
  original: 'Original audio transcript', previousOriginal: 'Previous successful transcript', failed: 'Audio transcription failed',
  empty: 'No speech recognized', audio: 'Audio', running: 'Transcribing…', unavailable: 'Transcript details unavailable',
  playbackUnavailable: 'This audio cannot be played in the current host; its transcript is still available.',
  playbackFailed: 'The browser could not play this audio.', download: 'Download original audio', copy: 'Copy original', copied: 'Copied',
  speech: 'Generated speech', speechGenerated: 'Speech generated', speechGenerating: 'Generating speech…', speechFailed: 'Speech generation failed',
  speechText: 'Spoken text', downloadSpeech: 'Download speech', generatedSpeech: 'Generated speech',
  play: 'Play', pause: 'Pause', seek: 'Audio progress',
  save: 'Save', saving: 'Saving…', saveFailed: 'Could not save. Check the configuration.', readOnly: 'Configuration is read-only.',
  configUnavailable: 'Configuration is currently unavailable.', overridden: 'Overridden', reset: 'Reset to default', invalid: 'Enter a valid value.',
}
export type LocaleKey = keyof typeof zh

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    /** Audio plugin copy. */
    audioTranscription: LocaleKey
  }
}
