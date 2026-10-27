import { test, expect } from '@playwright/test';
import { seedState } from './seed';
import { emptyState } from '../src/shared/workbench';

test('故事配音从 yovoice 筛选并导入独立音效素材', async ({ page }) => {
  const state = emptyState();
  const current = state.drafts[0];
  current.title = '当前故事';
  current.kind = 'story';
  current.timeline = { tracks: [{ id: 'track-1', name: '音轨 1', muted: false, clips: [] }] };
  const sfx = { ...current, id: 'sfx-work', title: '城市环境', kind: 'sfx' as const, timeline: undefined };
  const music = { ...current, id: 'music-work', title: '城市环境', kind: 'music' as const, timeline: undefined };
  const text = { ...current, id: 'text-work', title: '旁白作品', kind: 'text' as const, timeline: undefined };
  state.drafts = [current, sfx, music, text];
  const olderID = '1'.repeat(32), newestID = '2'.repeat(32), musicID = '3'.repeat(32), textID = '4'.repeat(32);
  state.history = [
    { id: olderID, title: '雷声版本', fileName: 'yovoice-source.wav', createdAt: '2026-10-01T10:00:00Z', duration: 1, settings: { ...sfx, title: '旧作品标题' } },
    { id: musicID, title: '雨滴版本', fileName: 'yovoice-source.wav', createdAt: '2026-10-04T10:00:00Z', duration: 1, settings: music },
    { id: textID, title: '朗读版本', fileName: 'yovoice-source.wav', createdAt: '2026-10-04T10:00:00Z', duration: 1, settings: text },
    { id: '5'.repeat(32), title: '分段音效', fileName: 'yovoice-source.wav', createdAt: '2026-10-05T10:00:00Z', duration: 1, settings: sfx, segment: { batchId: '6'.repeat(32), index: 0, cueId: 'cue-1', speakerId: 'speaker-1', speakerName: '旁白' } },
    { id: '7'.repeat(32), title: '当前作品版本', fileName: 'yovoice-source.wav', createdAt: '2026-10-05T10:00:00Z', duration: 1, settings: current },
    { id: newestID, title: '雨滴版本', fileName: 'yovoice-source.wav', createdAt: '2026-10-06T10:00:00Z', duration: 1, settings: { ...sfx, title: '旧作品标题' } },
  ];
  await page.goto('/');
  await page.evaluate(async () => {
    const modulePath = '/src/shared/lib/sound.ts';
    const { encodeWav } = await import(/* @vite-ignore */ modulePath);
    const audio = new AudioBuffer({ length: 24000, sampleRate: 24000, numberOfChannels: 1 });
    const samples = audio.getChannelData(0);
    for (let index = 0; index < samples.length; index++) samples[index] = Math.sin(index * 0.17) * 0.25;
    const blob = encodeWav(audio);
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('voice-workbench-audio', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('audio');
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result, transaction = db.transaction('audio', 'readwrite');
        transaction.objectStore('audio').put(blob, 'yovoice-source.wav');
        transaction.oncomplete = () => { db.close(); resolve(); };
        transaction.onerror = () => reject(transaction.error);
      };
    });
  });
  await seedState(page, state);
  await page.reload();
  await page.getByRole('button', { name: '当前故事', exact: true }).click();

  await page.getByRole('button', { name: '添加音频到音轨 1', exact: true }).click();
  await page.getByRole('menuitem', { name: '从 yovoice 添加', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const rows = dialog.locator('[data-generation-id]');
  await expect(dialog.getByRole('radio', { name: '音效生成', exact: true })).toBeChecked();
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toHaveAttribute('data-generation-id', newestID);
  await expect(rows.first()).toContainText('城市环境 · 雨滴版本');
  await expect(rows.first()).toContainText('00:01');

  const search = dialog.getByRole('textbox', { name: '搜索生成音频', exact: true });
  await search.fill('城市环境');
  await expect(rows).toHaveCount(2);
  await search.fill('雷声版本');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toHaveAttribute('data-generation-id', olderID);
  await search.fill('没有结果');
  await expect(rows).toHaveCount(0);
  await expect(dialog.getByText('暂无匹配的生成音频', { exact: true })).toBeVisible();
  await search.fill('');
  await dialog.getByRole('radio', { name: '音乐生成', exact: true }).click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toHaveAttribute('data-generation-id', musicID);
  await dialog.getByRole('radio', { name: '语音生成', exact: true }).click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toHaveAttribute('data-generation-id', textID);
  await dialog.getByRole('radio', { name: '音效生成', exact: true }).click();
  await expect(rows).toHaveCount(2);

  await dialog.locator(`[data-generation-id="${newestID}"]`).getByRole('button', { name: '添加', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.multitrack-clip')).toHaveText('城市环境 · 雨滴版本');
  await expect.poll(() => page.evaluate(id => {
    const stored = JSON.parse(localStorage.getItem('voice-workbench-v1')!);
    return stored.drafts.find((item: { id: string }) => item.id === id)?.timeline?.assets?.length ?? 0;
  }, current.id)).toBe(1);
  const stored = await page.evaluate(id => {
    const state = JSON.parse(localStorage.getItem('voice-workbench-v1')!);
    return state.drafts.find((item: { id: string }) => item.id === id).timeline;
  }, current.id);
  expect(stored.assets).toHaveLength(1);
  const asset = stored.assets[0];
  expect(asset).toMatchObject({ name: '城市环境 · 雨滴版本', duration: 1 });
  expect(asset.fileName).toMatch(new RegExp(`^import-${asset.id}\\.wav$`));
  expect(asset.fileName).not.toBe('yovoice-source.wav');
  expect(stored.tracks[0].clips[0]).toMatchObject({ assetId: asset.id, start: 0, offset: 0, duration: 1 });
  expect(stored.tracks[0].clips[0].generationId).toBeUndefined();

  await page.evaluate(async () => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('voice-workbench-audio', 1);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result, transaction = db.transaction('audio', 'readwrite');
        transaction.objectStore('audio').delete('yovoice-source.wav');
        transaction.oncomplete = () => { db.close(); resolve(); };
        transaction.onerror = () => reject(transaction.error);
      };
    });
  });
  await page.reload();
  await expect(page.locator('.multitrack-clip')).toHaveText('城市环境 · 雨滴版本');
  await page.getByRole('button', { name: '播放', exact: true }).click();
  await expect(page.getByRole('button', { name: '暂停', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '暂停', exact: true }).click();
});
