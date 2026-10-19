import { useEffect, useRef, useState } from 'react';
import { Button } from '@astryxdesign/core/Button';
import { HStack, VStack } from '@astryxdesign/core/Layout';
import { TextInput } from '@astryxdesign/core/TextInput';
import { TextArea } from '@astryxdesign/core/TextArea';
import { useTranslator } from '@astryxdesign/core/i18n';
import { Selector } from '../../shared/selector';
import { vosFetch } from '../../shared/lib/vos';
import { formatSize } from '../../shared/workbench';
import { SettingsGroup, SettingsRow } from '../../shared/ui/settings-group';

type MusicModel = { key: string; name: string; status: string; size: number; modelscope_repo: string; runtime_available: boolean; admission_ready: boolean; loaded: boolean; max_duration_seconds?: number; downloaded_bytes?: number; total_bytes?: number };

// 离开配乐页暂停轮询，但保留参数和已生成音频。
function useMusicModels(active: boolean) {
  const [models, setModels] = useState<MusicModel[]>([]), [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function update() {
      try {
        const response = await fetch('./api/v1/music-models', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error();
        const rows = await response.json() as MusicModel[];
        if (!controller.signal.aborted) { setModels(rows); setFailed(false); }
      } catch { if (!controller.signal.aborted) setFailed(true); }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => void update(), 3000); }
    }
    void update();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [active]);
  return { models, failed };
}

export function NativeMusicModels() {
  const t = useTranslator(), { models, failed } = useMusicModels(true);
  const [busy, setBusy] = useState(''), [error, setError] = useState('');
  async function manage(key: string, action: string) {
    setBusy(key); setError('');
    try {
      const response = await vosFetch(`/api/v1/music-models/${encodeURIComponent(key)}/${action}`, { method: 'POST' });
      if (!response.ok) throw new Error(t(response.status === 403 || response.status === 401 ? '@vvoice.music.adminRequired' : '@vvoice.music.manageFailed'));
    } catch (reason) { setError(reason instanceof Error ? reason.message : t('@vvoice.music.manageFailed')); }
    finally { setBusy(''); }
  }
  return <VStack data-testid="native-music-models"><SettingsGroup title={t('@vvoice.music.models')} description={t('@vvoice.music.modelsHint')}>
    {failed ? <p role="alert" className="settings-row">{t('@vvoice.models.inventoryError')}</p> : null}
    {error ? <p role="alert" className="settings-row">{error}</p> : null}
    {models.map(model => <SettingsRow key={model.key} label={model.name} hint={<><a href={`https://modelscope.cn/models/${model.modelscope_repo}`} target="_blank" rel="noreferrer">{model.modelscope_repo}</a> · {formatSize(model.size)} · {t(`@vvoice.music.status.${model.status}`)}</>}>
      {!model.runtime_available ? <small>{t('@vvoice.music.gpuRequired')}</small> : null}
      {model.status === 'downloading' ? <small>{formatSize(model.downloaded_bytes ?? 0)} / {formatSize(model.total_bytes ?? model.size)}</small> : null}
      <Button size="sm" label={t(model.status === 'downloading' ? '@yovoice.action.pause' : model.status === 'ready' ? '@vvoice.runtime.unload' : '@yovoice.settings.downloadModel')} isDisabled={!!busy || model.status === 'verifying' || model.loaded} isLoading={busy === model.key} onClick={() => void manage(model.key, model.status === 'downloading' ? 'stop' : model.status === 'ready' ? 'unload' : 'pull')} />
    </SettingsRow>)}
  </SettingsGroup></VStack>;
}

export function BackgroundMusic({ active, openModels }: { active: boolean; openModels: () => void }) {
  const t = useTranslator(), { models, failed } = useMusicModels(active);
  const [model, setModel] = useState('stable-audio-3-small-music'), [prompt, setPrompt] = useState(''), [negative, setNegative] = useState('vocals, speech, distortion');
  const [duration, setDuration] = useState('30'), [seed, setSeed] = useState(''), [bpm, setBpm] = useState(''), [key, setKey] = useState(''), [meter, setMeter] = useState(''), [instrumental, setInstrumental] = useState('true'), [format, setFormat] = useState('wav');
  const [result, setResult] = useState<{ url: string; format: string }>(), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const resultRef = useRef('');
  useEffect(() => () => { if (resultRef.current) URL.revokeObjectURL(resultRef.current); }, []);
  const selected = models.find(item => item.key === model);
  async function generate() {
    const seconds = Number(duration), tempo = bpm.trim() ? Number(bpm) : undefined, random = seed.trim() ? Number(seed) : undefined;
    if (!prompt.trim() || !Number.isFinite(seconds) || seconds < 10 || seconds > (selected?.max_duration_seconds ?? 300) || (tempo !== undefined && (!Number.isInteger(tempo) || tempo < 20 || tempo > 300)) || (random !== undefined && (!Number.isInteger(random) || random < -1 || random > 2147483647))) { setError(t('@vvoice.music.invalid')); return; }
    setBusy(true); setError('');
    try {
      const response = await vosFetch('/v1/audio/music/generations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model, prompt, duration: seconds, negative_prompt: negative, seed: random, bpm: tempo, key, time_signature: meter, instrumental: instrumental === 'true', response_format: format }) });
      if (!response.ok) throw new Error(t(response.status === 503 ? '@vvoice.music.notReady' : response.status === 429 ? '@vvoice.music.busy' : response.status === 422 ? '@vvoice.music.invalid' : '@vvoice.music.failed'));
      const blob = await response.blob();
      if (!blob.size || !blob.type.startsWith('audio/')) throw new Error(t('@vvoice.music.failed'));
      const url = URL.createObjectURL(blob);
      if (resultRef.current) URL.revokeObjectURL(resultRef.current);
      resultRef.current = url; setResult({ url, format });
    } catch (reason) { setError(reason instanceof Error ? reason.message : t('@vvoice.music.failed')); }
    finally { setBusy(false); }
  }
  return <VStack className="settings-page" gap={5} style={{ overflowY: 'auto', overscrollBehavior: 'contain' }} data-testid="background-music">
    <VStack as="header" gap={2} style={{ height: 'auto', flexShrink: 0, alignItems: 'stretch' }}><h1>{t('@vvoice.music.title')}</h1><p>{t('@vvoice.music.hint')}</p></VStack>
    {failed ? <p role="alert">{t('@vvoice.models.inventoryError')}</p> : null}
    <HStack gap={3} vAlign="end" wrap="wrap"><Selector label={t('@vvoice.music.model')} value={model} options={models.map(item => ({ value: item.key, label: item.name }))} onChange={setModel} isDisabled={busy} /><Button label={t('@vvoice.nav.models')} onClick={openModels} /></HStack>
    <TextArea label={t('@vvoice.music.prompt')} value={prompt} onChange={setPrompt} rows={4} maxLength={4000} isDisabled={busy} />
    <TextArea label={t('@vvoice.music.negative')} value={negative} onChange={setNegative} rows={2} maxLength={4000} isDisabled={busy} />
    <HStack gap={4} wrap="wrap"><TextInput label={t('@vvoice.music.duration')} value={duration} onChange={setDuration} isDisabled={busy} /><TextInput label={t('@vvoice.music.seed')} value={seed} onChange={setSeed} isDisabled={busy} /><TextInput label={t('@vvoice.music.bpm')} value={bpm} onChange={setBpm} isDisabled={busy} /></HStack>
    <HStack gap={4} wrap="wrap"><TextInput label={t('@vvoice.music.key')} value={key} onChange={setKey} isDisabled={busy} /><Selector label={t('@vvoice.music.meter')} value={meter} options={['', '2/4', '3/4', '4/4', '6/8'].map(value => ({ value, label: value || t('@vvoice.music.auto') }))} onChange={setMeter} isDisabled={busy} /><Selector label={t('@vvoice.music.instrumental')} value={instrumental} options={[{ value: 'true', label: t('@vvoice.music.yes') }, { value: 'false', label: t('@vvoice.music.no') }]} onChange={setInstrumental} isDisabled={busy} /><Selector label={t('@vvoice.music.format')} value={format} options={['wav', 'flac']} onChange={setFormat} isDisabled={busy} /></HStack>
    <small>{t('@vvoice.music.controlsHint')}</small>
    <Button variant="primary" label={t(busy ? '@vvoice.music.generating' : '@vvoice.music.generate')} isLoading={busy} isDisabled={!prompt.trim() || selected?.status !== 'ready' || !selected?.runtime_available || !selected.admission_ready} onClick={() => void generate()} />
    {selected?.status !== 'ready' ? <p role="status">{t('@vvoice.music.installFirst')}</p> : !selected.runtime_available ? <p role="status">{t('@vvoice.music.gpuRequired')}</p> : null}
    {selected?.status === 'ready' && selected.runtime_available && !selected.admission_ready ? <p role="status">{t('@vvoice.music.notReady')}</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {result ? <VStack gap={3}><audio controls src={result.url} aria-label={t('@vvoice.music.result')} /><a href={result.url} download={`music.${result.format}`}>{t('@vvoice.music.download')}</a></VStack> : null}
  </VStack>;
}
