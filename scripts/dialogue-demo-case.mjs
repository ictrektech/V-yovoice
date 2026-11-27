#!/usr/bin/env node
/**
 * 实时对话演示案例：在真实 VOS 页面内播放合成语音，收集对话、截图、延时和卸载证据。
 *
 * 用法：
 *   node scripts/dialogue-demo-case.mjs --cdp http://127.0.0.1:9222
 *   node scripts/dialogue-demo-case.mjs --launch
 */
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const require = createRequire(new URL('../web/package.json', import.meta.url));
const { chromium } = require('@playwright/test');

const root = path.resolve(import.meta.dirname, '..');
const options = parseArgs(process.argv.slice(2));
const vosUrl = options.vos || 'https://10.144.144.232:1180';
const out = path.resolve(options.out || `/tmp/vvoice-dialogue-demo-${Date.now()}`);
const clipsPath = path.resolve(options.clips || path.join(root, 'scripts/fixtures/dialogue-demo-clips.json'));
const maxSeconds = Number(options['max-seconds'] || 150);
const waitUnload = options['no-wait-unload'] !== true;
const keepOpen = options['keep-open'] !== false;

mkdirSync(out, { recursive: true });
const clips = JSON.parse(readFileSync(clipsPath, 'utf8'));
const clipLimit = Math.min(clips.clips.length, Number(options['clip-limit'] || clips.clips.length));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

let browser;
let page;
let launched = false;

try {
  if (options.cdp) {
    browser = await chromium.connectOverCDP(options.cdp);
    page = browser.contexts()[0]?.pages().find(item => item.url().includes('1180')) ?? browser.contexts()[0]?.pages()[0];
    if (!page) throw new Error('CDP 浏览器里没有可用页面');
  } else {
    launched = true;
    browser = await chromium.launchPersistentContext(
      options.profile || path.join(process.env.HOME, '.cache/v-yovoice-dialogue-demo/profile'),
      {
        headless: false,
        ignoreHTTPSErrors: true,
        viewport: { width: 1440, height: 920 },
        args: ['--start-maximized'],
      },
    );
    page = browser.pages()[0] ?? await browser.newPage();
    await page.goto(vosUrl + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    console.log('请在浏览器里登录 VOS；登录后脚本会自动打开 V-Voice。');
  }

  await page.bringToFront();
  const frame = await openDialogue(page);
  const iframe = page.locator('iframe[src*="/app/com.ictrek.v-voice"]');
  await resetDialogue(page, frame);
  await installHarness(frame, clips);
  await sleep(500);
  await screenshot(page, iframe, out, '01-idle');
  const t0 = Date.now();
  await frame.getByTestId('dialogue-start').click();
  console.log('已开始对话');
  await sleep(200);
  await screenshot(page, iframe, out, '02-loading');

  const started = await waitFor(
    () => frame.evaluate(() => {
      const events = window.__wsLog || [];
      const startedEvent = events.find(event => event.type === 'started');
      if (startedEvent) return startedEvent;
      return events.filter(event => event.type === 'error').at(-1) || null;
    }),
    120000,
    '会话启动',
  );
  if (started.type === 'error') throw new Error(`会话启动失败：${started.code || ''} ${started.message || ''}`.trim());
  const tStarted = Date.now();
  console.log(`模型加载 ${((tStarted - t0) / 1000).toFixed(1)} 秒`);
  await sleep(800);
  await screenshot(page, iframe, out, '03-active-empty');

  await sleep(1500);
  const greeting = await audioInfo(frame);
  if (greeting.count > 0) await settleAudio(frame, { quietMs: 2000, maxMs: 15000 });

  const turns = [];
  for (let index = 0; index < clipLimit; index++) {
    if ((Date.now() - t0) / 1000 > maxSeconds) break;
    const before = await transcript(frame);
    const beforeLog = await frame.evaluate(() => window.__wsLog.length);
    const play = await playClip(frame, index);
    const audio = await settleAudio(frame, { quietMs: 2500, maxMs: 45000, afterPerf: play.end });
    const reply = await settleTranscript(frame, before.length, { quietMs: 1500, maxMs: 8000, requireGrowth: false });
    const events = await frame.evaluate(count => window.__wsLog.slice(count), beforeLog);
    const texts = events.filter(event => event.type === 'text' && event.t > play.start && event.text);
    const firstText = texts[0]?.t ?? null;
    const lastText = texts.at(-1)?.t ?? null;
    const added = reply.text.slice(before.length).trim();
    turns.push({
      index: index + 1,
      userText: clips.clips[index].text,
      clipSeconds: Number(play.seconds.toFixed(2)),
      replyText: added,
      audioLatencySeconds: audio.firstLoud == null ? null : Number((Math.max(0, audio.firstLoud - play.end) / 1000).toFixed(2)),
      textLatencySeconds: firstText == null ? null : Number((Math.max(0, firstText - play.end) / 1000).toFixed(2)),
      replyAudioSeconds: audio.firstLoud == null || audio.lastLoud == null ? null : Number(((audio.lastLoud - audio.firstLoud) / 1000).toFixed(2)),
      replySeconds: firstText == null || lastText == null ? null : Number(((lastText - firstText) / 1000).toFixed(2)),
    });
    console.log(`第 ${index + 1} 轮：${added.slice(0, 40)}${added.length > 40 ? '…' : ''}`);
    if (index === 0) await screenshot(page, iframe, out, '04-active-turn1');
    if (index === 1) await screenshot(page, iframe, out, '05-active-turn2');
    await sleep(800);
  }

  await screenshot(page, iframe, out, '06-active-final');
  const hangup = frame.getByTestId('dialogue-hangup');
  if (await hangup.count()) await hangup.click();
  const end = await waitFor(
    () => frame.evaluate(() => window.__wsLog.find(event => event.type === 'end') || null),
    30000,
    '会话结束',
  );
  const tEnd = Date.now();
  await sleep(1200);

  const fullTranscript = await transcript(frame);
  const statusAfterEnd = await dialogueStatus(frame);
  await screenshot(page, iframe, out, '07-ended');
  const evidence = {
    device: 'tc232',
    app: 'com.ictrek.v-voice',
    profile: 'amd-cuda',
    image: options.image || 'amd_cu128_0.0.40',
    vosUrl,
    startedAt: new Date(t0).toISOString(),
    modelLoadSeconds: Number(((tStarted - t0) / 1000).toFixed(2)),
    sessionSeconds: Number(((tEnd - t0) / 1000).toFixed(2)),
    endReason: end.reason || 'complete',
    turns,
    transcript: fullTranscript,
    statusAfterEnd,
    screenshots: ['01-idle', '02-loading', '03-active-empty', '04-active-turn1', '05-active-turn2', '06-active-final', '07-ended']
      .map(name => `${name}.png`),
  };
  writeFileSync(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log(`会话 ${evidence.sessionSeconds} 秒，转写 ${fullTranscript.length} 字`);
  console.log('结束状态', JSON.stringify(statusAfterEnd));

  if (waitUnload) {
    const unloadStart = Date.now();
    let last = statusAfterEnd;
    for (let attempt = 0; attempt < 36 && last.state !== 'unloaded'; attempt++) {
      await sleep(5000);
      last = await dialogueStatus(frame);
      console.log(`卸载检查 ${Math.round((Date.now() - unloadStart) / 1000)} 秒：${last.state}`);
    }
    evidence.statusAfterUnload = last;
    evidence.unloadWaitSeconds = Number(((Date.now() - unloadStart) / 1000).toFixed(1));
    writeFileSync(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));
  }

  console.log(`证据目录：${out}`);
  console.log(JSON.stringify({
    modelLoadSeconds: evidence.modelLoadSeconds,
    sessionSeconds: evidence.sessionSeconds,
    turns: turns.map(turn => ({
      user: turn.userText,
      reply: turn.replyText,
      latency: turn.replyLatencySeconds,
    })),
    statusAfterEnd,
    statusAfterUnload: evidence.statusAfterUnload,
  }, null, 2));
} finally {
  if (launched && !keepOpen) await browser?.close();
}

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index++) {
    const item = argv[index];
    if (!item.startsWith('--')) continue;
    const key = item.slice(2);
    const value = argv[index + 1]?.startsWith('--') ? true : argv[++index] ?? true;
    result[key] = value;
  }
  return result;
}

async function openDialogue(target) {
  if (target.url().includes('/auth/login')) {
    console.log('等待 VOS 登录完成…');
    await target.waitForURL(url => !url.href.includes('/auth/login'), { timeout: 600000 });
    await sleep(1500);
  }
  let frame = findAppFrame(target);
  if (!frame && target.url().includes('/dashboard')) {
    const drawer = target.getByText('应用抽屉', { exact: true });
    if (await drawer.count()) {
      await drawer.first().click();
      await sleep(1200);
    }
  }
  if (!frame) {
    const app = target.getByText('V-Voice', { exact: true });
    if (await app.count()) {
      await app.first().click();
      await sleep(2500);
    }
  }
  frame = findAppFrame(target);
  if (!frame) {
    const dashboard = target.getByText('首页', { exact: true });
    if (await dashboard.count()) {
      await dashboard.first().click();
      await sleep(1000);
      const drawer = target.getByText('应用抽屉', { exact: true });
      if (await drawer.count()) await drawer.first().click();
      await sleep(1200);
      const app = target.getByText('V-Voice', { exact: true });
      if (await app.count()) await app.first().click();
      await sleep(2500);
      frame = findAppFrame(target);
    }
  }
  if (!frame) {
    await target.waitForFunction(() => [...document.querySelectorAll('iframe')].some(item => item.src.includes('/app/com.ictrek.v-voice')), null, { timeout: 60000 });
    frame = findAppFrame(target);
  }
  if (!frame) throw new Error('没有找到 V-Voice 应用 iframe');
  if (!(await frame.getByTestId('dialogue-start').count())) {
    const nav = frame.getByRole('button', { name: '实时对话', exact: true });
    if (!(await nav.count())) throw new Error('没有找到“实时对话”入口');
    await nav.first().click();
    await frame.getByTestId('dialogue-start').waitFor({ timeout: 15000 });
  }
  return frame;
}

function findAppFrame(target) {
  return target.frames().find(item => item.url().includes('/app/com.ictrek.v-voice/'));
}

async function resetDialogue(target, frame) {
  const other = frame.getByRole('button', { name: '语音生成', exact: true });
  const dialogue = frame.getByRole('button', { name: '实时对话', exact: true });
  if (await other.count()) {
    await other.first().click();
    await sleep(600);
    await dialogue.first().click();
    await frame.getByTestId('dialogue-start').waitFor({ timeout: 15000 });
  } else {
    await target.reload({ waitUntil: 'domcontentloaded' });
    await sleep(1500);
  }
}

async function installHarness(frame, payload) {
  await frame.evaluate(async value => {
    const real = Object.getOwnPropertyDescriptor(Navigator.prototype, 'mediaDevices').get.call(navigator);
    const mic = { ctx: null, dest: null, clips: value.clips };
    window.__demoMic = mic;
    const fake = {
      enumerateDevices: async () => [{ kind: 'audioinput', deviceId: 'demo-mic', label: 'Demo Mic', groupId: 'demo' }],
      addEventListener: (...args) => real.addEventListener(...args),
      removeEventListener: (...args) => real.removeEventListener(...args),
      dispatchEvent: event => real.dispatchEvent(event),
      getUserMedia: async () => {
        const context = new AudioContext({ sampleRate: value.sampleRate });
        await context.resume();
        mic.ctx = context;
        mic.dest = context.createMediaStreamDestination();
        return mic.dest.stream;
      },
    };
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: fake });
    real.dispatchEvent(new Event('devicechange'));
    if (window.__wsPeakVersion !== 2) {
      window.__wsPeakVersion = 2;
      window.__wsWrapped = true;
      window.__wsLog = [];
      const Native = window.WebSocket;
      window.WebSocket = class extends Native {
        constructor(...args) {
          super(...args);
          this.addEventListener('message', event => {
            const t = performance.now();
            if (typeof event.data === 'string') {
              try {
                const message = JSON.parse(event.data);
                window.__wsLog.push({
                  t,
                  type: message.type,
                  text: typeof message.text === 'string' ? message.text.slice(0, 2000) : undefined,
                  code: message.code,
                  message: message.message,
                  reason: message.reason,
                });
              } catch {}
            } else {
              const samples = new Int16Array(event.data);
              let peak = 0;
              for (let offset = 0; offset < samples.length; offset += 8) {
                peak = Math.max(peak, Math.abs(samples[offset]));
              }
              window.__wsLog.push({ t, type: 'audio', bytes: event.data.byteLength, peak });
            }
          });
        }
        send(data) {
          const t = performance.now();
          if (typeof data === 'string') {
            try {
              const message = JSON.parse(data);
              window.__wsLog.push({ t, out: true, type: message.type });
            } catch {}
          } else {
            window.__wsLog.push({ t, out: true, type: 'pcm', bytes: data.byteLength });
          }
          return super.send(data);
        }
      };
    } else {
      window.__wsLog = [];
    }
  }, payload);
  await frame.waitForFunction(() => {
    const button = document.querySelector('[data-testid="dialogue-start"]');
    return button && !button.disabled;
  }, null, { timeout: 15000 });
}

async function playClip(frame, index) {
  return frame.evaluate(async position => {
    const mic = window.__demoMic;
    const clip = mic.clips[position];
    const raw = atob(clip.pcm);
    const bytes = new Uint8Array(raw.length);
    for (let offset = 0; offset < raw.length; offset++) bytes[offset] = raw.charCodeAt(offset);
    const pcm = new Int16Array(bytes.buffer);
    const buffer = mic.ctx.createBuffer(1, pcm.length, 24000);
    const channel = buffer.getChannelData(0);
    for (let offset = 0; offset < pcm.length; offset++) channel[offset] = pcm[offset] / 32768;
    const source = mic.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(mic.dest);
    const start = performance.now();
    source.start();
    await new Promise(resolve => { source.onended = resolve; });
    return { start, end: performance.now(), seconds: buffer.duration };
  }, index);
}

async function audioInfo(frame) {
  return frame.evaluate(() => {
    const audio = (window.__wsLog || []).filter(event => event.type === 'audio');
    return {
      count: audio.length,
      last: audio.length ? audio.at(-1).t : 0,
      loud: audio.filter(event => (event.peak || 0) >= 120).length,
    };
  });
}

async function settleAudio(frame, { quietMs, maxMs, afterPerf = 0 }) {
  const started = Date.now();
  let sawSpeech = false;
  let firstLoud = null;
  let lastLoud = null;
  let lastFrame = null;
  while (Date.now() - started < maxMs) {
    const info = await frame.evaluate(after => {
      const audio = (window.__wsLog || []).filter(event => event.type === 'audio' && event.t > after);
      const loud = audio.filter(event => (event.peak || 0) >= 120);
      return {
        count: audio.length,
        loudCount: loud.length,
        firstLoud: loud.length ? loud[0].t : null,
        lastLoud: loud.length ? loud.at(-1).t : null,
        lastFrame: audio.length ? audio.at(-1).t : null,
        now: performance.now(),
      };
    }, afterPerf);
    if (info.loudCount > 0) {
      sawSpeech = true;
      if (firstLoud == null) firstLoud = info.firstLoud;
      lastLoud = info.lastLoud;
    }
    lastFrame = info.lastFrame;
    if (sawSpeech && lastLoud != null && info.now - lastLoud >= quietMs) {
      return { sawSpeech, firstLoud, lastLoud, lastFrame, waitMs: info.now - lastLoud };
    }
    await sleep(250);
  }
  return { sawSpeech, firstLoud, lastLoud, lastFrame, waitMs: null };
}

async function settleTranscript(frame, beforeLength, { quietMs, maxMs, requireGrowth = true }) {
  const started = Date.now();
  let lastLength = beforeLength;
  let lastChange = Date.now();
  let firstGrowth = null;
  while (Date.now() - started < maxMs) {
    const text = await transcript(frame);
    if (text.length !== lastLength) {
      lastLength = text.length;
      lastChange = Date.now();
      if (text.length > beforeLength && firstGrowth == null) firstGrowth = Date.now();
    }
    if ((!requireGrowth || firstGrowth != null) && Date.now() - lastChange >= quietMs) {
      return { text, firstGrowthMs: firstGrowth == null ? null : firstGrowth - started };
    }
    await sleep(250);
  }
  return { text: await transcript(frame), firstGrowthMs: firstGrowth == null ? null : firstGrowth - started };
}

async function transcript(frame) {
  return frame.locator('.dialogue-transcript').innerText().catch(() => '');
}

async function dialogueStatus(frame) {
  return frame.evaluate(async () => {
    const base64url = value => btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    const verifier = base64url(crypto.getRandomValues(new Uint8Array(32)));
    const state = base64url(crypto.getRandomValues(new Uint8Array(24)));
    const nonce = base64url(crypto.getRandomValues(new Uint8Array(24)));
    const challenge = base64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)));
    const oauth = window.vos_platform.api.v1000.oauth2;
    const authorization = await oauth.authorize({
      client_id: 'com.ictrek.v-voice',
      response_type: 'code',
      scope: 'openid profile email',
      state,
      nonce,
      code_challenge: challenge,
      code_challenge_method: 'S256',
    });
    const tokens = await oauth.token({
      grant_type: 'authorization_code',
      client_id: 'com.ictrek.v-voice',
      code: authorization.code,
      code_verifier: verifier,
    });
    const response = await fetch('/app/com.ictrek.v-voice/api/v1/dialogue/status', {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
    return response.json();
  });
}

async function screenshot(target, iframe, directory, name) {
  await target.screenshot({ path: path.join(directory, `${name}-full.png`), fullPage: true });
  await iframe.screenshot({ path: path.join(directory, `${name}.png`) }).catch(async () => {
    const frame = findAppFrame(target);
    await frame?.locator('body').screenshot({ path: path.join(directory, `${name}.png`) });
  });
}

async function waitFor(read, timeout, label) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await read();
    if (value) return value;
    await sleep(250);
  }
  throw new Error(`等待${label}超时`);
}
