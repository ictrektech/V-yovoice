import { test, expect } from '@playwright/test';
import { resolve } from 'node:path';
import { emptyState } from '../src/shared/workbench';

test('VOS 语音识别页在所选节点部署、登记模型并核对转写回执', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true' || !process.env.VVOICE_SERVICE_DIST, '需要 VOS 构建');
  const targets = [
    { kind: 'ssh', id: 'gpu-a', profile: 'dgx-spark', node_name: 'Spark A' },
    { kind: 'ssh', id: 'gpu-b', profile: 'dgx-spark', node_name: 'Spark B' },
  ];
  const selected = {
    deployment_id: 'second-deployment', executor_id: 'second-executor', node_id: 'worker-b',
    model_id: 'sensevoice-int8', profile: 'dgx-spark', node_name: 'Spark B',
  };
  let deployed = false;
  let prepared = false;
  let calls = 0;
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
  });
  await page.route('**/studio-api/call', route => route.fulfill({ json: { result: { state: emptyState(), catalog: [], engine: { version: 'v0.9.1', minimum: 'v0.9.1' }, desktop: false } } }));
  await page.route('**/service/**', route => {
    const path = new URL(route.request().url()).pathname.split('/service/')[1];
    if (path === 'runtime-config.js') return route.fulfill({ contentType: 'text/javascript', body: '' });
    return route.fulfill({ path: resolve(process.env.VVOICE_SERVICE_DIST!, path || 'index.html') });
  });
  await page.route('**/api/v1/models', route => route.fulfill({ json: [
    { key: 'sensevoice-int8', name: 'SenseVoice INT8', kind: 'asr', status: 'ready', languages: [] },
  ] }));
  await page.route('**/api/v1/hotwords', route => route.fulfill({ json: [] }));
  await page.route('**/api/v1/models/sensevoice-int8/input-limits', route => route.fulfill({ json: {
    limits: null, max_upload_bytes: 2_000_000,
  } }));
  await page.route('**/v1/audio/transcriptions', route => {
    expect(route.request().postData()).toContain('sensevoice-int8');
    return route.fulfill({ json: { text: '主节点转写结果' } });
  });
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [] }));
  await page.route('**/api/v1/compute/deployments', route => {
    expect(route.request().headers().authorization).toBe('Bearer fixture-token');
    if (route.request().method() === 'POST') {
      expect(route.request().postDataJSON()).toMatchObject({ kind: 'ssh', node_id: 'gpu-b' });
      deployed = true;
      return route.fulfill({ json: { id: selected.deployment_id } });
    }
    return route.fulfill({ json: {
      targets, models: [{ model_id: selected.model_id, name: 'SenseVoice INT8', kind: 'asr', ready: true }], images: { 'dgx-spark': 'registry.example/voice:thor' },
      deployments: deployed ? [{ id: selected.deployment_id, target_id: 'gpu-b', target_kind: 'ssh',
        profile: 'dgx-spark', node_name: 'Spark B', image: 'registry.example/voice:thor', state: 'running',
        registered_models: prepared ? [selected.model_id] : [], preparations: [] }] : [],
    } });
  });
  await page.route('**/api/v1/compute/deployments/second-deployment/models', route => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({ model_id: 'sensevoice-int8', weight_mode: 'copy' });
    prepared = true;
    return route.fulfill({ json: selected });
  });
  await page.route('**/api/v1/voice/compute/placements', route => route.fulfill({ json: { can_force_admission: true, items: [
    { ...selected, deployment_id: 'first-deployment', executor_id: 'first-executor', node_id: 'worker-a', node_name: 'Spark A' },
    ...(prepared ? [selected] : []),
  ] } }));
  await page.route('**/api/v1/voice/compute/transcriptions', route => {
    expect(route.request().headers().authorization).toBe('Bearer fixture-token');
    const body = route.request().postDataBuffer()?.toString() ?? '';
    expect(body).toContain('name="deployment_id"\r\n\r\nsecond-deployment');
    expect(body).toContain('name="executor_id"\r\n\r\nsecond-executor');
    if (calls === 0) expect(body).not.toContain('name="force_admission"');
    else expect(body).toContain('name="force_admission"\r\n\r\ntrue');
    return route.fulfill({ json: { ...selected, node_id: ++calls === 1 ? 'worker-a' : 'worker-b',
      task_id: 'qa-task', transcription: { text: '这是一条测试转写' } } });
  });

  await page.goto('/');
  await page.getByTestId('nav-asr').click();
  await page.getByRole('button', { name: '节点部署管理', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox', { name: '目标节点与 Profile' }).click();
  await page.getByRole('option', { name: 'Spark B · dgx-spark' }).click();
  await dialog.getByRole('button', { name: '部署后端' }).click();
  await dialog.getByRole('combobox', { name: '权重方式 · Spark B' }).click();
  await page.getByRole('option', { name: '传输到节点' }).click();
  await dialog.getByRole('button', { name: '准备并登记模型' }).click();
  await expect(dialog.getByText(/SenseVoice INT8 · 可用/)).toBeVisible();
  await dialog.getByRole('button', { name: '关闭' }).click();

  const form = page.frameLocator('iframe[title="语音识别 ASR"]');
  const nodes = form.getByRole('combobox', { name: '执行节点' });
  await expect(nodes).toHaveValue('local');
  await expect(nodes.locator('option[value=local]')).toHaveText('主节点（本机）');
  await form.locator('input[type=file]').first().setInputFiles({ name: 'qa.wav', mimeType: 'audio/wav', buffer: Buffer.from('fixture') });
  await form.getByRole('button', { name: '开始识别' }).click();
  await expect(form.getByText('主节点转写结果')).toBeVisible();
  await expect(form.getByText('实际执行节点 主节点（本机）')).toBeVisible();
  await nodes.selectOption('second-deployment:second-executor');
  await form.getByRole('button', { name: '开始识别' }).click();
  await expect(form.getByText('执行回执与所选节点或执行器不一致。')).toBeVisible();
  await expect(form.getByText('这是一条测试转写')).toHaveCount(0);
  await form.getByRole('checkbox', { name: '本次直接放行' }).check();
  await form.getByRole('button', { name: '开始识别' }).click();
  await expect(form.getByText('实际执行节点 Spark B · worker-b')).toBeVisible();
  await expect(form.getByText('这是一条测试转写')).toBeVisible();
});

test('VOS 合成与声纹表单可选择实际执行节点', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true' || !process.env.VVOICE_SERVICE_DIST, '需要 VOS 构建');
  const tts = { deployment_id: 'tts-deployment', executor_id: 'tts-executor', node_id: 'spark-b',
    model_id: 'vits-zh', node_name: 'Spark B', profile: 'dgx-spark' };
  const speaker = { ...tts, executor_id: 'speaker-executor', model_id: 'speaker-campplus-zh-en' };
  await page.addInitScript(() => {
    localStorage.setItem('v-voice-creator-locale', 'zh-CN');
    window.vos_platform = { getState: async () => ({ locale: 'zh-CN' }), api: { v1000: { oauth2: {
      authorize: async input => ({ code: 'fixture-code', state: input.state }),
      token: async () => ({ access_token: 'fixture-token', expires_in: 3600 }),
    } } } };
  });
  await page.route('**/studio-api/call', route => route.fulfill({ json: { result: { state: emptyState(), catalog: [], engine: { version: 'v0.9.1', minimum: 'v0.9.1' }, desktop: false } } }));
  await page.route('**/service/**', route => {
    const path = new URL(route.request().url()).pathname.split('/service/')[1];
    if (path === 'runtime-config.js') return route.fulfill({ contentType: 'text/javascript', body: '' });
    return route.fulfill({ path: resolve(process.env.VVOICE_SERVICE_DIST!, path || 'index.html') });
  });
  await page.route('**/api/v1/scheduler/binding', route => route.fulfill({ json: { configured: true } }));
  await page.route('**/api/v1/creative-models', route => route.fulfill({ json: [] }));
  await page.route('**/api/v1/speakers', route => route.fulfill({ json: [] }));
  await page.route('**/api/v1/hotwords', route => route.fulfill({ json: [] }));
  await page.route('**/api/v1/models', route => route.fulfill({ json: [
    { key: tts.model_id, name: 'VITS', kind: 'tts', status: 'ready', languages: ['zh'], voices: { default: { sid: 0, language: 'zh' } } },
    { key: speaker.model_id, name: 'CAM++', kind: 'speaker', status: 'ready', languages: ['zh'] },
  ] }));
  await page.route('**/api/v1/compute/placements?*', route => {
    const kind = new URL(route.request().url()).searchParams.get('task_type');
    return route.fulfill({ json: { items: [kind === 'voice.synthesize' ? tts : speaker] } });
  });
  await page.route('**/api/v1/compute/speech', route => {
    expect(route.request().postDataJSON()).toMatchObject({ executor_id: tts.executor_id, deployment_id: tts.deployment_id });
    return route.fulfill({ contentType: 'audio/mpeg', body: 'fixture', headers: {
      'X-Execution-Node': tts.node_id, 'X-Execution-Executor': tts.executor_id, 'X-Execution-Deployment': tts.deployment_id,
    } });
  });
  await page.route('**/api/v1/compute/speakers/identify', route => {
    expect(route.request().postData()).toContain(speaker.executor_id);
    return route.fulfill({ json: { ...speaker, result: { identified: false, ranked: [] } } });
  });

  await page.goto('/');
  await page.getByTestId('nav-tts').click();
  const synth = page.frameLocator('iframe[title^="语音合成"]');
  const synthNodes = synth.getByRole('combobox', { name: '执行节点' });
  await expect(synthNodes).toHaveValue('local');
  await synthNodes.selectOption(`${tts.deployment_id}:${tts.executor_id}`);
  await synth.getByRole('button', { name: '生成语音' }).click();
  await expect(synth.getByText('实际执行节点 Spark B · spark-b')).toBeVisible();

  await page.getByTestId('nav-speaker').click();
  const voices = page.frameLocator('iframe[title^="声纹识别"]');
  const voiceNodes = voices.getByRole('combobox', { name: '执行节点' });
  await expect(voiceNodes).toHaveValue('local');
  await voiceNodes.selectOption(`${speaker.deployment_id}:${speaker.executor_id}`);
  await voices.locator('input[type=file]').nth(1).setInputFiles({ name: 'speaker.wav', mimeType: 'audio/wav', buffer: Buffer.from('sample') });
  await voices.getByRole('button', { name: '开始识别' }).click();
  await expect(voices.getByText('实际执行节点 Spark B · spark-b')).toBeVisible();
});
