// 使用真实浏览器解码与重采样，只替换识别响应；不加载模型或访问生产服务。
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = path.resolve(import.meta.dirname, '..');
const webRequire = createRequire(path.join(root, 'web/package.json'));
const frontendRequire = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = webRequire('@playwright/test');
const { createServer } = await import(pathToFileURL(frontendRequire.resolve('vite')).href);
const server = await createServer({ root: path.join(root, 'frontend'), configFile: path.join(root, 'frontend/vite.config.ts'), server: { host: '127.0.0.1', port: 0 } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.route('**/api/**', route => route.fulfill({ json: [] }));
  await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/`);
  const result = await page.evaluate(async soundPath => {
    const { transcribeUpload } = await import('/src/asr-upload.ts');
    const { api } = await import('/src/api.ts');
    const { encodeWav, encodeWavFrames } = await import(soundPath);
    const source = new AudioBuffer({ length: 41.234375 * 48000, sampleRate: 48000, numberOfChannels: 2 });
    source.getChannelData(1).fill(0.5);
    // 保留双声道原文件，确保输入超过原来的上传和采样率阈值。
    const mono = new Uint8Array(await encodeWav(source).arrayBuffer());
    const original = new Uint8Array(44 + source.length * 4);
    original.set(mono.subarray(0, 44));
    const header = new DataView(original.buffer);
    header.setUint32(4, original.length - 8, true); header.setUint16(22, 2, true);
    header.setUint32(28, 48000 * 4, true); header.setUint16(32, 4, true); header.setUint32(40, original.length - 44, true);
    for (let i = 0; i < source.length; i++) header.setInt16(46 + i * 4, 16384, true);
    const file = new File([original], 'original.wav', { type: 'audio/wav' });
    const form = new FormData(); form.append('file', file); form.append('model', 'sensevoice-int8'); form.append('response_format', 'verbose_json');
    let limits = { duration_seconds: 20, sample_rate: 24000, input_bytes: 1048576, hotwords_characters: 0 };
    api.inputLimits = async () => ({ limits, max_upload_bytes: 200 * 1048576 });
    let sent = [];
    let active = 0;
    let maxActive = 0;
    const responses = ['Hello', 'world', 'again'];
    api.transcribe = async segment => {
      active++; maxActive = Math.max(maxActive, active);
      const blob = segment.get('file');
      const buffer = await blob.arrayBuffer();
      const view = new DataView(buffer);
      const samples = (buffer.byteLength - 44) / 2;
      sent.push({ size: blob.size, samples, rate: view.getUint32(24, true), channels: view.getUint16(22, true), sample: view.getInt16(44 + 100 * 2, true), model: segment.get('model'), format: segment.get('response_format') });
      active--;
      return { text: responses[sent.length - 1] || '尾' };
    };
    const progress = [];
    const text = await transcribeUpload(form, message => progress.push(message), new AbortController().signal);
    const timeLimited = [...sent];
    // 字节上限比时长更小，同时覆盖不能整除的分段位置，不能丢失或重复采样。
    limits = { ...limits, input_bytes: 100044 };
    sent = [];
    await transcribeUpload(form, () => {}, new AbortController().signal);
    const byteLimited = [...sent];
    let cancelledCalls = 0;
    const controller = new AbortController();
    api.transcribe = async () => { cancelledCalls++; controller.abort(); return { text: 'first' }; };
    let cancelled = false;
    try { await transcribeUpload(form, () => {}, controller.signal); } catch (error) { cancelled = error.name === 'AbortError'; }
    let failedCalls = 0;
    api.transcribe = async () => { failedCalls++; throw new Error('busy'); };
    let failed = false;
    try { await transcribeUpload(form, () => {}, new AbortController().signal); } catch (error) { failed = error.message === 'busy'; }
    // 原有秒数裁切仍走同一编码实现。
    const crop = await encodeWav(source, 0, 0.125).arrayBuffer();
    const frameCrop = await encodeWavFrames(source, 0, 6000).arrayBuffer();
    return { originalBytes: file.size, text, timeLimited, byteLimited, maxActive, progress, cancelledCalls, cancelled, failedCalls, failed,
      sameCrop: new Uint8Array(crop).every((value, i) => value === new Uint8Array(frameCrop)[i]) };
  }, '/@fs' + path.join(root, 'web/src/shared/lib/sound.ts'));
  assert(result.originalBytes > 1048576);
  assert.equal(result.text, 'Hello world again');
  assert.equal(result.maxActive, 1);
  assert.equal(result.timeLimited.length, 3);
  for (const part of result.timeLimited) {
    assert(part.size <= 1048576 && part.samples <= 20 * 16000);
    assert.equal(part.rate, 16000); assert.equal(part.channels, 1);
    assert(Math.abs(part.sample - 8192) < 8);
    assert.equal(part.model, 'sensevoice-int8'); assert.equal(part.format, 'verbose_json');
  }
  for (const parts of [result.timeLimited, result.byteLimited]) assert.equal(parts.reduce((sum, part) => sum + part.samples, 0), 659750);
  assert(result.byteLimited.every(part => part.size <= 100044));
  assert(result.progress.some(message => message.includes('第 3 段，共 3 段')));
  assert(result.cancelled && result.cancelledCalls === 1);
  assert(result.failed && result.failedCalls === 1);
  assert(result.sameCrop);
  // 再经过真实页面与 fetch，确认用户点击识别会进入分段流程。
  const ui = await browser.newPage();
  await ui.route('**/api/**', route => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith('/input-limits')) return route.fulfill({ json: { limits: { duration_seconds: 20, sample_rate: 24000, input_bytes: 1048576, hotwords_characters: 0 }, max_upload_bytes: 200 * 1048576 } });
    return route.fulfill({ json: pathname.endsWith('/models') ? [
      { key: 'qwen3-asr-0.6b', name: 'Qwen3', kind: 'asr', status: 'ready', inference_ready: false },
      { key: 'sensevoice-int8', name: 'SenseVoice', kind: 'asr', status: 'ready', inference_ready: true },
    ] : [] });
  });
  let uploaded = 0;
  await ui.route('**/v1/audio/transcriptions', route => {
    const body = route.request().postDataBuffer();
    const start = body.indexOf('RIFF');
    assert(start >= 0 && body.readUInt32LE(start + 24) === 16000);
    assert(body.readUInt32LE(start + 40) <= 20 * 16000 * 2);
    return route.fulfill({ json: { text: ['你好，', '世界。', '测试。'][uploaded++] } });
  });
  const wav = Buffer.alloc(44 + 41 * 48000 * 4);
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(2, 22);
  wav.writeUInt32LE(48000, 24); wav.writeUInt32LE(48000 * 4, 28); wav.writeUInt16LE(4, 32);
  wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(wav.length - 44, 40);
  await ui.goto(`http://127.0.0.1:${server.httpServer.address().port}/?standalone=1&page=asr&locale=zh-CN`);
  await ui.getByLabel('音频文件').setInputFiles({ name: 'asr_en.wav', mimeType: 'audio/wav', buffer: wav });
  assert.equal(await ui.getByLabel('ASR 模型').inputValue(), 'sensevoice-int8');
  assert.notEqual(await ui.getByRole('option', { name: /Qwen3/ }).getAttribute('disabled'), null);
  await ui.getByRole('button', { name: '开始识别', exact: true }).click();
  await ui.getByText('你好，世界。测试。', { exact: true }).waitFor();
  assert.equal(uploaded, 3);
  await ui.getByRole('button', { name: '开始识别', exact: true }).click();
  await ui.getByRole('button', { name: '取消识别', exact: true }).click();
  await ui.getByText('已取消识别。', { exact: true }).waitFor();
  await ui.close();
  // 全部模型仅下载、尚未获准时，显示原因且禁止提交识别。
  const blocked = await browser.newPage();
  await blocked.route('**/api/**', route => route.fulfill({ json: route.request().url().endsWith('/models') ? [
    { key: 'qwen3-asr-0.6b', name: 'Qwen3', kind: 'asr', status: 'ready', inference_ready: false, inference_error: 'Model executor is not approved' },
  ] : [] }));
  await blocked.goto(`http://127.0.0.1:${server.httpServer.address().port}/?standalone=1&page=asr&locale=zh-CN`);
  await blocked.getByText('此模型尚未获准在当前设备执行，请先选择其他模型。', { exact: true }).waitFor();
  await blocked.getByLabel('音频文件').setInputFiles({ name: 'asr.wav', mimeType: 'audio/wav', buffer: wav });
  assert(await blocked.getByRole('button', { name: '开始识别', exact: true }).isDisabled());
  await blocked.close();
  console.log('PASS: 48 kHz stereo file >1 MiB; complete mono resampling, time/byte bounds, sequential uploads, text merge, progress, cancellation, failure and existing WAV cropping');
} finally {
  await browser?.close();
  await server.close();
}
