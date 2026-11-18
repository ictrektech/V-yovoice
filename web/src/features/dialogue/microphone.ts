import type { TranslatorFn } from '@astryxdesign/core/i18n';

export type MicrophoneState = 'checking' | 'available' | 'missing' | 'unsupported';

export async function inspectMicrophone(
  media: Pick<MediaDevices, 'enumerateDevices'> | undefined = navigator.mediaDevices,
): Promise<Exclude<MicrophoneState, 'checking'>> {
  if (!media?.enumerateDevices) return 'unsupported';
  try {
    const devices = await media.enumerateDevices();
    return devices.some(device => device.kind === 'audioinput') ? 'available' : 'missing';
  } catch {
    return 'unsupported';
  }
}

export function microphoneError(t: TranslatorFn, value: unknown): string {
  const name = value instanceof DOMException
    ? value.name
    : value && typeof value === 'object' && 'name' in value
      ? String((value as { name: unknown }).name)
      : '';
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return t('@yovoice.error.micNotFound');
  if (name === 'NotAllowedError' || name === 'SecurityError') return t('@yovoice.error.micDeniedBrowser');
  return t('@yovoice.error.micFailed', { detail: value instanceof Error ? value.message : String(value) });
}
