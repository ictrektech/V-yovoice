import { api } from './api'
import { decodeAudio, encodeWavFrames } from '../../web/src/shared/lib/sound'

// 在浏览器准备音频；每段仍走原接口并单独申请、释放计算许可。
export async function transcribeUpload(form: FormData, progress: (message: string) => void, signal: AbortSignal): Promise<string> {
  const file = form.get('file')
  const model = form.get('model')
  if (!(file instanceof File) || typeof model !== 'string') throw new Error('请选择音频和模型。')
  const { limits, max_upload_bytes: maximum } = await api.inputLimits(model, signal)
  signal.throwIfAborted()
  if (file.size > maximum) throw new Error('音频文件超过上传上限，请先拆分文件。')
  if (!limits) return (await api.transcribe(form, signal)).text

  const rate = 16000
  const frames = Math.floor(Math.min(limits.duration_seconds * rate, (Math.min(limits.input_bytes, maximum) - 44) / 2))
  if (!Number.isFinite(frames) || frames < 1 || limits.sample_rate < rate) throw new Error('模型输入限制不支持音频分段，请重新校准模型。')
  progress('正在转换音频…')
  let audio: AudioBuffer
  try { audio = await decodeAudio(file, rate) }
  catch { signal.throwIfAborted(); throw new Error('浏览器无法解码此音频，请转换为 WAV 或 MP3 后重试。') }
  signal.throwIfAborted()
  if (!audio.length) throw new Error('音频文件为空。')

  const parts: string[] = []
  const total = Math.ceil(audio.length / frames)
  for (let offset = 0; offset < audio.length; offset += frames) {
    signal.throwIfAborted()
    progress(`正在识别第 ${parts.length + 1} 段，共 ${total} 段…`)
    const segment = new FormData()
    for (const [key, value] of form.entries()) if (key !== 'file') segment.append(key, value)
    const end = Math.min(audio.length, offset + frames)
    segment.append('file', encodeWavFrames(audio, offset, end), 'segment.wav')
    const result = await api.transcribe(segment, signal)
    signal.throwIfAborted()
    parts.push(result.text.trim())
  }
  return parts.filter(Boolean).reduce((text, part) => {
    // 中日韩文字直接相接；英文等单词之间保留空格。
    const separator = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\p{Punctuation}]$/u.test(text) &&
      /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(part) ? '' : ' '
    return text ? text + separator + part : part
  }, '')
}
