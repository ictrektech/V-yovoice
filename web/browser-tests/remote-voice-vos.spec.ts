import { test, expect } from '@playwright/test';
import { emptyState } from '../src/shared/workbench';

test('VOS 语音识别页在所选节点部署、登记模型并核对转写回执', async ({ page }) => {
  test.skip(process.env.VITE_VOS !== 'true', '需要 VOS 构建');
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
  await page.route('**/service/**', route => route.fulfill({ contentType: 'text/html', body: '<html><body>Speech controls</body></html>' }));
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
      targets, images: { 'dgx-spark': 'registry.example/voice:thor' },
      deployments: deployed ? [{ id: selected.deployment_id, target_id: 'gpu-b', target_kind: 'ssh',
        profile: 'dgx-spark', node_name: 'Spark B', image: 'registry.example/voice:thor', state: 'running' }] : [],
    } });
  });
  await page.route('**/api/v1/compute/deployments/second-deployment/prepare', route => {
    expect(route.request().method()).toBe('POST');
    prepared = true;
    return route.fulfill({ json: selected });
  });
  await page.route('**/api/v1/voice/compute/placements', route => route.fulfill({ json: { items: [
    { ...selected, deployment_id: 'first-deployment', executor_id: 'first-executor', node_id: 'worker-a', node_name: 'Spark A' },
    ...(prepared ? [selected] : []),
  ] } }));
  await page.route('**/api/v1/voice/compute/transcriptions', route => {
    expect(route.request().headers().authorization).toBe('Bearer fixture-token');
    const body = route.request().postDataBuffer()?.toString() ?? '';
    expect(body).toContain('name="deployment_id"\r\n\r\nsecond-deployment');
    expect(body).toContain('name="executor_id"\r\n\r\nsecond-executor');
    return route.fulfill({ json: { ...selected, node_id: ++calls === 1 ? 'worker-a' : 'worker-b',
      task_id: 'qa-task', transcription: { text: '这是一条测试转写' } } });
  });

  await page.goto('/');
  await page.getByTestId('nav-asr').click();
  await page.getByRole('button', { name: '远端节点', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: '管理部署' }).click();
  await dialog.getByRole('combobox', { name: '目标节点与 Profile' }).click();
  await page.getByRole('option', { name: 'Spark B · dgx-spark' }).click();
  await dialog.getByRole('button', { name: '部署后端' }).click();
  await dialog.getByRole('button', { name: '准备并登记 SenseVoice' }).click();
  await expect(dialog.getByText(/sensevoice-int8 · 可转写/)).toBeVisible();
  await dialog.getByRole('button', { name: '转写', exact: true }).click();
  await dialog.getByRole('combobox', { name: '模型与执行节点' }).click();
  await page.getByRole('option', { name: 'sensevoice-int8 · Spark B · dgx-spark' }).click();
  await dialog.locator('input[type=file]').setInputFiles({ name: 'qa.wav', mimeType: 'audio/wav', buffer: Buffer.from('fixture') });
  await dialog.getByRole('button', { name: '开始转写' }).click();
  await expect(dialog.getByRole('alert')).toContainText('执行回执与所选节点或执行器不一致');
  await expect(dialog.getByText('这是一条测试转写')).toHaveCount(0);
  await dialog.getByRole('button', { name: '开始转写' }).click();
  await expect(dialog.getByText('实际执行节点 Spark B · worker-b')).toBeVisible();
  await expect(dialog.getByText('这是一条测试转写')).toBeVisible();
});
