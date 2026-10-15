import { describe, expect, it } from 'vitest'
import { languageNames, translateText } from './messages'

describe('interface translations', () => {
  it('translates creative API documentation without changing parameter names', () => {
    for (const text of ['创作语音与调度', '声音克隆、设计与情绪控制', 'V-Router 与 V-Scheduler', '参考音频的 Base64 编码，不接受服务器路径。', '音乐、编曲与任务', '音乐生成', '编曲渲染', '任务查询与取消', '结果与参考音色']) {
      expect(translateText(text, 'en-US')).not.toMatch(/[\u3400-\u9fff]/)
      expect(translateText(text, 'zh-TW')).not.toBe(text)
    }
    expect(translateText('reference_audio', 'zh-TW')).toBe('reference_audio')
  })
  it('translates fixed labels without changing technical text', () => {
    expect(translateText('模型管理', 'en-US')).toBe('Model management')
    expect(translateText('模型管理', 'zh-TW')).toBe('模型管理')
    expect(translateText('/v1/audio/transcriptions', 'en-US')).toBe('/v1/audio/transcriptions')
  })

  it('translates count-dependent labels', () => {
    expect(translateText(' 个已就绪模型', 'en-US')).toBe(' ready models')
    expect(translateText('12 个已就绪模型', 'en-US')).toBe('12 ready models')
    expect(translateText('7 个可用音色', 'zh-TW')).toBe('7 個可用音色')
    expect(translateText('42 / 20000 字符', 'en-US')).toBe('42 / 20000 characters')
  })

  it('translates composed lists of language names and unmapped language codes', () => {
    for (const languages of [Object.keys(languageNames), ['auto', 'zh', 'yue', 'en', 'ja', 'ko'], ['en', 'ko', 'ja', 'ar', 'bg', 'cs', 'da', 'de', 'el', 'es', 'et', 'fi', 'fr', 'hi', 'hr', 'hu', 'id', 'it', 'lt', 'lv', 'nl', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sv', 'tr', 'uk', 'vi']]) {
      const source = languages.map(language => languageNames[language] || language).join('、')
      expect(translateText(source, 'zh-CN')).toBe(source)
      expect(translateText(source, 'en-US')).not.toMatch(/[\u3400-\u9fff、]/)
    }
    expect(translateText('自动检测、中文、粤语、英语、日语、韩语', 'en-US')).toBe('Auto-detect, Chinese, Cantonese, English, Japanese, Korean')
    expect(translateText('自动检测、粤语、英语', 'zh-TW')).toBe('自動偵測、粵語、英語')
  })

  it('translates all ASR endpoint capability combinations', () => {
    for (const hotwords of [false, true]) {
      for (const streaming of [false, true]) {
        const source = `转写 / 翻译${hotwords ? ' / 热词增强' : ''}${streaming ? ' / 实时流式' : ''}`
        expect(translateText(source, 'en-US')).toBe(`Transcribe / translate${hotwords ? ' / hotwords' : ''}${streaming ? ' / real-time streaming' : ''}`)
        expect(translateText(source, 'zh-TW')).toBe(`轉寫 / 翻譯${hotwords ? ' / 熱詞增強' : ''}${streaming ? ' / 即時串流' : ''}`)
        expect(translateText(source, 'zh-CN')).toBe(source)
      }
    }
  })

  it('translates voice-option language labels without modifying voice IDs or arbitrary text', () => {
    expect(translateText('zf_xiaoxiao · 中文 · SID 0', 'en-US')).toBe('zf_xiaoxiao · Chinese · SID 0')
    expect(translateText('粤语、英语', 'en-US')).toBe('Cantonese, English')
    expect(translateText('公司名称、中文', 'en-US')).toBe('公司名称、中文')
  })
})
