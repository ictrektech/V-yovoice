import { useEffect, useRef, useState } from 'react';
import { Button } from '@astryxdesign/core/Button';
import { HStack, VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { Server } from 'lucide-react';
import { schedulerFetch, vosFetch } from '../../shared/lib/vos';
import { Selector } from '../../shared/selector';
import { AppDialog, ConfirmDelete } from '../../shared/ui/app-dialog';

type Placement = { deployment_id: string; executor_id: string; node_id: string; profile: string; node_name?: string | null; model_id: string };
type Receipt = Placement & { task_id: string; transcription: { text: string } };
type Target = { id: string; kind: 'ssh' | 'cluster'; profile: string; node_name?: string | null };
type Deployment = { id: string; target_id: string; target_kind: Target['kind']; profile: string; node_name?: string | null; image: string; state: string; last_error?: string | null };
type Overview = { targets: Target[]; images: Record<string, string>; deployments: Deployment[] };
const listPath = '/api/v1/voice/compute/placements';
const deploymentsPath = '/api/v1/compute/deployments';
const targetKey = (target: Target) => `${target.kind}:${target.id}:${target.profile}`;
const placementKey = (placement: Placement) => `${placement.deployment_id}:${placement.executor_id}`;
const matches = (receipt: Pick<Receipt, 'node_id' | 'deployment_id' | 'executor_id'>, selected: Placement) =>
  receipt.node_id === selected.node_id && receipt.deployment_id === selected.deployment_id && receipt.executor_id === selected.executor_id;

async function payload<T>(response: Promise<Response>): Promise<T> {
  const result = await response;
  if (result.ok) return result.json() as Promise<T>;
  const body: { detail?: unknown; code?: unknown } = await result.json().catch(() => ({}));
  const code = body.detail ?? body.code;
  throw new Error(typeof code === 'string' ? code : String(result.status));
}

const errorLabels: Record<string, string> = {
  '403': 'adminRequired',
  VOICE_COMPUTE_ADMIN_REQUIRED: 'adminRequired',
  BACKEND_EXECUTOR_TARGET_NOT_READY: 'nodeNotReady',
  VOICE_COMPUTE_PLACEMENT_UNAVAILABLE: 'placementUnavailable',
  VOICE_COMPUTE_PLACEMENT_MISMATCH: 'placementMismatch',
  VOICE_COMPUTE_DEPLOYMENT_NOT_FOUND: 'placementUnavailable',
  VOICE_COMPUTE_SOURCE_MODEL_UNAVAILABLE: 'sourceMissing',
  BACKEND_TASKS_ACTIVE: 'tasksActive',
  BACKEND_IMAGE_PULL_FAILED: 'imagePullFailed',
  VOICE_COMPUTE_TRANSCRIPTION_TIMEOUT: 'timeout',
};

export function RemoteVoiceButton({ initialManage = false }: { initialManage?: boolean }) {
  const t = useTranslator();
  const [open, setOpen] = useState(false);
  return <>
    <Button variant="secondary" size="sm" icon={<Server />} label={t('@yovoice.remoteVoice.title')} onClick={() => setOpen(true)} />
    {open ? <RemoteVoice initialManage={initialManage} onClose={() => setOpen(false)} /> : null}
  </>;
}

function RemoteVoice({ initialManage, onClose }: { initialManage: boolean; onClose: () => void }) {
  const t = useTranslator();
  const tr = (key: string) => t(`@yovoice.remoteVoice.${key}`);
  const [manage, setManage] = useState(initialManage);
  const [placements, setPlacements] = useState<Placement[]>([]);
  const [overview, setOverview] = useState<Overview>();
  const [selected, setSelected] = useState('');
  const [target, setTarget] = useState('');
  const [file, setFile] = useState<File>();
  const [result, setResult] = useState<{ receipt: Receipt; placement: Placement }>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [remove, setRemove] = useState<Deployment>();
  const inference = useRef<AbortController | null>(null);
  const operation = useRef(false);
  const requestKeys = useRef(new Map<string, string>());
  const selection = placements.find(item => placementKey(item) === selected);
  const eligible = (overview?.targets ?? []).filter(item =>
    !overview?.deployments.some(row => row.target_id === item.id && row.target_kind === item.kind && row.state !== 'removed'));
  const destination = eligible.find(item => targetKey(item) === target);

  async function load(withManagement: boolean, signal?: AbortSignal) {
    const { items } = await payload<{ items: Placement[] }>(schedulerFetch(listPath, { signal }));
    if (!signal?.aborted) setPlacements(items);
    if (withManagement) {
      const catalog = await payload<Overview>(vosFetch(deploymentsPath, { signal }));
      if (!signal?.aborted) setOverview(catalog);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    const refresh = async () => {
      if (operation.current) return;
      try {
        await load(manage, controller.signal);
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void refresh();
    const timer = manage ? window.setInterval(() => void refresh(), 4500) : undefined;
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [manage]);
  useEffect(() => () => inference.current?.abort(), []);

  function switchMode(next: boolean) {
    setError('');
    setLoading(true);
    setManage(next);
  }

  async function run(label: string, action: () => Promise<void>) {
    if (operation.current) return;
    operation.current = true;
    setError('');
    setBusy(label);
    try { await action(); }
    catch (reason) {
      if (!inference.current?.signal.aborted) setError(reason instanceof Error ? reason.message : '');
    } finally {
      inference.current = null;
      operation.current = false;
      setBusy('');
    }
  }

  function deploy() {
    if (!destination) return;
    const requestKey = requestKeys.current.get(target) ?? crypto.randomUUID();
    requestKeys.current.set(target, requestKey);
    void run('deploy', async () => {
      await payload(vosFetch(deploymentsPath, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: destination.kind, node_id: destination.id, request_key: requestKey }),
      }));
      requestKeys.current.delete(target);
      setTarget('');
      await load(true);
    });
  }

  function control(id: string, action: 'start' | 'stop' | 'prepare' | 'remove') {
    void run(action, async () => {
      const path = deploymentsPath + '/' + encodeURIComponent(id);
      await payload(vosFetch(action === 'remove' ? path : path + '/' + action, { method: action === 'remove' ? 'DELETE' : 'POST' }));
      setRemove(undefined);
      await load(true);
    });
  }

  function transcribe() {
    if (!file || !selection) return;
    void run('transcribe', async () => {
      setResult(undefined);
      const controller = new AbortController();
      inference.current = controller;
      const data = new FormData();
      data.set('file', file);
      data.set('deployment_id', selection.deployment_id);
      data.set('executor_id', selection.executor_id);
      const receipt = await payload<Receipt>(schedulerFetch('/api/v1/voice/compute/transcriptions', { method: 'POST', body: data, signal: controller.signal }));
      if (!matches(receipt, selection)) throw new Error('VOICE_COMPUTE_PLACEMENT_MISMATCH');
      setResult({ receipt, placement: selection });
    });
  }

  const labelError = (code: string) => errorLabels[code] ? tr(errorLabels[code]) : `${tr('error')} (${code})`;
  return <>
    <AppDialog title={tr('title')} width={720} onClose={onClose} busy={!!busy} error={error ? labelError(error) : undefined}>
      <HStack gap={2} wrap="wrap">
        <Button label={tr('use')} variant={manage ? 'ghost' : 'secondary'} isDisabled={!!busy || !manage} onClick={() => switchMode(false)} />
        <Button label={tr('manage')} variant={manage ? 'secondary' : 'ghost'} isDisabled={!!busy || manage} onClick={() => switchMode(true)} />
        <Button label={tr('refresh')} variant="ghost" isDisabled={!!busy} onClick={() => void run('refresh', () => load(manage))} />
      </HStack>
      {loading ? <p role="status">{tr('loading')}</p> : manage ? <>
        {overview ? <>
          <HStack gap={2} wrap="wrap" vAlign="end">
            <Selector label={tr('target')} placeholder={tr('selectTarget')} options={eligible.map(item => ({
              value: targetKey(item), label: `${item.node_name || item.id} · ${item.profile}`,
            }))} value={target} onChange={setTarget} isDisabled={!!busy || !eligible.length} />
            <Button label={tr('deploy')} variant="primary" isDisabled={!!busy || !destination} isLoading={busy === 'deploy'} onClick={deploy} />
          </HStack>
          {destination ? <small>{overview.images[destination.profile]}</small> : null}
          {overview.deployments.filter(row => row.state !== 'removed').map(row => {
            const model = placements.find(item => item.deployment_id === row.id);
            const running = row.state === 'running' && !row.last_error;
            return <VStack key={row.id} gap={2}>
              <strong>{row.node_name || row.target_id} · {row.profile}</strong>
              <small>{row.image}</small>
              <p role="status">{tr(`state.${row.state}`)}{model ? ` · ${model.model_id} · ${tr('registered')}` : ''}</p>
              {row.last_error ? <p role="alert">{labelError(row.last_error)}</p> : null}
              <HStack gap={2} wrap="wrap">
                {running && !model ? <Button label={tr('prepare')} variant="primary" isDisabled={!!busy} isLoading={busy === 'prepare'} onClick={() => control(row.id, 'prepare')} /> : null}
                {row.state === 'failed' || row.state === 'stopped' ? <Button label={tr('start')} isDisabled={!!busy} onClick={() => control(row.id, 'start')} /> : null}
                {row.state === 'running' || row.state === 'pending' ? <Button label={tr('stop')} isDisabled={!!busy} onClick={() => control(row.id, 'stop')} /> : null}
                {row.state !== 'deleting' && row.state !== 'stopping' ? <Button label={tr('remove')} variant="destructive" isDisabled={!!busy} onClick={() => setRemove(row)} /> : null}
              </HStack>
            </VStack>;
          })}
          {busy === 'prepare' ? <p role="status">{tr('preparing')}</p> : null}
        </> : null}
      </> : <>
        {placements.length ? <Selector label={tr('placement')} placeholder={tr('selectPlacement')}
          options={placements.map(item => ({ value: placementKey(item), label: `${item.model_id} · ${item.node_name || item.node_id} · ${item.profile}` }))}
          value={selection ? selected : ''} isDisabled={!!busy} onChange={value => { setSelected(value); setResult(undefined); setError(''); }} /> : <p>{tr('empty')}</p>}
        {selection ? <>
          <label>{tr('audio')} <input type="file" accept=".wav,.flac,.mp3,.ogg,.m4a" disabled={!!busy}
            onChange={event => { setFile(event.target.files?.[0]); setResult(undefined); }} /></label>
          <HStack gap={2} wrap="wrap">
            <Button label={tr('transcribe')} variant="primary" isDisabled={!file || !!busy} isLoading={busy === 'transcribe'} onClick={transcribe} />
            {busy === 'transcribe' ? <Button label={t('@yovoice.action.cancel')} onClick={() => inference.current?.abort()} /> : null}
          </HStack>
        </> : null}
        {result ? <VStack gap={2}>
          <p role="status">{tr('actualNode')} {result.placement.node_name || result.receipt.node_id} · {result.receipt.node_id}</p>
          <p>{result.receipt.transcription.text}</p>
          <Button label={tr('copy')} variant="secondary" onClick={() => void run('copy', () => navigator.clipboard.writeText(result.receipt.transcription.text))} />
        </VStack> : null}
      </>}
    </AppDialog>
    {remove ? <ConfirmDelete title={tr('remove')} description={`${remove.node_name || remove.target_id} · ${tr('removeDescription')}`}
      confirmLabel={tr('remove')} busy={busy === 'remove'} onClose={() => setRemove(undefined)} onConfirm={() => control(remove.id, 'remove')} /> : null}
  </>;
}
