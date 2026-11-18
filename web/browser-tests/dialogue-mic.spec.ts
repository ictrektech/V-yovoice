import { expect, test } from '@playwright/test';
import type { TranslatorFn } from '@astryxdesign/core/i18n';
import { inspectMicrophone, microphoneError } from '../src/features/dialogue/microphone';

test('麦克风检测区分可用、缺失和不支持', async () => {
  await expect(inspectMicrophone(undefined)).resolves.toBe('unsupported');
  await expect(inspectMicrophone({
    enumerateDevices: async () => [],
  })).resolves.toBe('missing');
  await expect(inspectMicrophone({
    enumerateDevices: async () => [{ kind: 'audiooutput' } as MediaDeviceInfo],
  })).resolves.toBe('missing');
  await expect(inspectMicrophone({
    enumerateDevices: async () => [{ kind: 'audioinput' } as MediaDeviceInfo],
  })).resolves.toBe('available');
  await expect(inspectMicrophone({
    enumerateDevices: async () => { throw new Error('blocked'); },
  })).resolves.toBe('unsupported');
});

test('麦克风错误映射为本地化提示', () => {
  const calls: Array<{ key: string; values?: Record<string, unknown> }> = [];
  const t = ((key: string, values?: Record<string, unknown>) => {
    calls.push({ key, values });
    return key;
  }) as unknown as TranslatorFn;

  expect(microphoneError(t, new DOMException('missing', 'NotFoundError'))).toBe('@yovoice.error.micNotFound');
  expect(microphoneError(t, new DOMException('denied', 'NotAllowedError'))).toBe('@yovoice.error.micDeniedBrowser');
  expect(microphoneError(t, new Error('device busy'))).toBe('@yovoice.error.micFailed');
  expect(calls.at(-1)).toEqual({ key: '@yovoice.error.micFailed', values: { detail: 'device busy' } });
});
