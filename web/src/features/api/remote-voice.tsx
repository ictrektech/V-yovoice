import { useEffect, useRef, useState } from 'react';
import { Button } from '@astryxdesign/core/Button';
import { HStack, VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { Server } from 'lucide-react';
import { vosFetch } from '../../shared/lib/vos';
import { Selector } from '../../shared/selector';
import { AppDialog, ConfirmDelete } from '../../shared/ui/app-dialog';

type Target = { id: string; kind: 'ssh' | 'cluster'; profile: string; node_name?: string | null };
type WeightMode = 'auto' | 'shared' | 'copy';
type Preparation = {
  model_id: string; weight_mode: WeightMode; weight_source: 'shared' | 'copy' | null;
  state: 'preparing' | 'registered' | 'failed' | 'interrupted'; phase: string;
  received_bytes: number; total_bytes: number; error: string | null;
};
type Deployment = { id: string; target_id: string; target_kind: Target['kind']; profile: string; node_name?: string | null; image: string; state: string; last_error?: string | null; preparations: Preparation[]; registered_models: string[] };
type ComputeModel = { model_id: string; name: string; kind: string; ready: boolean; status: string; progress?: number; error?: string | null };
type Overview = { models: ComputeModel[]; targets: Target[]; images: Record<string, string>; deployments: Deployment[] };
const deploymentsPath = '/api/v1/compute/deployments';
const weights = ['auto', 'shared', 'copy'] as const;
const targetKey = (target: Target) => `${target.kind}:${target.id}:${target.profile}`;

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
  BACKEND_SHARED_MODEL_HUB_UNAVAILABLE: 'nfsUnavailable',
  VOICE_COMPUTE_SOURCE_NOT_SHARED: 'nfsSourceMissing',
  VOICE_COMPUTE_PREPARATION_INTERRUPTED: 'preparationInterrupted',
  VOICE_COMPUTE_PREPARATION_ACTIVE: 'preparationActive',
  BACKEND_EXECUTOR_TARGET_NOT_READY: 'nodeNotReady',
  VOICE_COMPUTE_PLACEMENT_UNAVAILABLE: 'placementUnavailable',
  VOICE_COMPUTE_PLACEMENT_MISMATCH: 'placementMismatch',
  VOICE_COMPUTE_DEPLOYMENT_NOT_FOUND: 'placementUnavailable',
  VOICE_COMPUTE_SOURCE_MODEL_UNAVAILABLE: 'sourceMissing',
  BACKEND_TASKS_ACTIVE: 'tasksActive',
  BACKEND_IMAGE_PULL_FAILED: 'imagePullFailed',
  VOICE_COMPUTE_TRANSCRIPTION_TIMEOUT: 'timeout',
};

export function RemoteVoiceButton() {
  const t = useTranslator();
  const [open, setOpen] = useState(false);
  return <>
    <Button variant="secondary" size="sm" icon={<Server />} label={t('@yovoice.remoteVoice.manage')} onClick={() => setOpen(true)} />
    {open ? <RemoteVoice onClose={() => setOpen(false)} /> : null}
  </>;
}

function RemoteVoice({ onClose }: { onClose: () => void }) {
  const t = useTranslator();
  const tr = (key: string) => t(`@yovoice.remoteVoice.${key}`);
  const [overview, setOverview] = useState<Overview>();
  const [modelIds, setModelIds] = useState<Record<string, string>>({});
  const [modes, setModes] = useState<Record<string, WeightMode>>({});
  const [target, setTarget] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [remove, setRemove] = useState<{ row: Deployment; model?: string }>();
  const operation = useRef(false);
  const requestKeys = useRef(new Map<string, string>());
  const eligible = (overview?.targets ?? []).filter(item =>
    !overview?.deployments.some(row => row.target_id === item.id && row.target_kind === item.kind && row.state !== 'removed'));
  const destination = eligible.find(item => targetKey(item) === target);

  async function load(signal?: AbortSignal) {
    const catalog = await payload<Overview>(vosFetch(deploymentsPath, { signal }));
    if (!signal?.aborted) setOverview(catalog);
  }

  useEffect(() => {
    const controller = new AbortController();
    let checking = false;
    const refresh = async () => {
      if (operation.current || checking) return;
      checking = true;
      try { await load(controller.signal); }
      catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '');
      } finally { checking = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);

  async function run(label: string, action: () => Promise<unknown>) {
    if (operation.current) return;
    operation.current = true;
    setBusy(label);
    setError('');
    try { await action(); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : ''); }
    finally { operation.current = false; setBusy(''); }
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
    });
  }

  function control(id: string, action: 'start' | 'stop' | 'prepare' | 'remove' | 'removeModel', modelId?: string, mode?: WeightMode) {
    void run(`${action}:${id}`, async () => {
      const path = deploymentsPath + '/' + encodeURIComponent(id);
      const suffix = { start: '/start', stop: '/stop', prepare: '/models', remove: '', removeModel: '/models/' + encodeURIComponent(modelId ?? '') }[action];
      await payload(vosFetch(path + suffix, mode ? {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_id: modelId, weight_mode: mode }),
      } : { method: action === 'remove' || action === 'removeModel' ? 'DELETE' : 'POST' }));
      setRemove(undefined);
    });
  }

  const labelError = (code: string) => errorLabels[code] ? tr(errorLabels[code]) : `${tr('error')} (${code})`;
  return <>
    <AppDialog title={tr('manage')} width={720} onClose={onClose} busy={!!busy} error={error ? labelError(error) : undefined}
      actions={<Button label={tr('refresh')} variant="ghost" isDisabled={!!busy} onClick={() => void run('refresh', async () => {})} />}>
      {!overview && !error ? <p role="status">{tr('loading')}</p> : null}
      {overview ? <>
        <VStack gap={2}>
          <strong>{tr('primary')}</strong>
          {(overview.models ?? []).map(item => {
            const downloading = item.status === 'downloading';
            const verifying = item.status === 'verifying';
            const path = '/api/v1/models/' + encodeURIComponent(item.model_id);
            return <HStack key={item.model_id} gap={2} wrap="wrap" vAlign="center">
              <strong>{item.name}</strong>
              <small role="status">{item.ready ? tr('registered') : tr(`primaryState.${item.status}`)}
                {downloading && item.progress != null ? ` · ${Math.floor(item.progress * 100)}%` : ''}</small>
              {item.error ? <small role="alert">{item.error}</small> : null}
              {!item.ready && !verifying ? <Button label={tr(downloading ? 'cancelDownload' : 'install')}
                isDisabled={!!busy} onClick={() => void run(`install:${item.model_id}`, () =>
                  payload(vosFetch(path + (downloading ? '/stop' : '/pull'), { method: 'POST' })))} /> : null}
            </HStack>;
          })}
        </VStack>
        <HStack gap={2} wrap="wrap" vAlign="end">
          <Selector label={tr('target')} placeholder={tr('selectTarget')} options={eligible.map(item => ({
            value: targetKey(item), label: `${item.node_name || item.id} · ${item.profile}`,
          }))} value={target} onChange={setTarget} isDisabled={!!busy || !eligible.length} />
          <Button label={tr('deploy')} variant="primary" isDisabled={!!busy || !destination} isLoading={busy === 'deploy'} onClick={deploy} />
        </HStack>
        {destination ? <small>{overview.images[destination.profile]}</small> : null}
        {overview.deployments.filter(row => row.state !== 'removed').map(row => {
          const name = row.node_name || row.target_id;
          const preparations = row.preparations ?? [];
          const registered = row.registered_models ?? [];
          const running = row.state === 'running' && !row.last_error;
          const preparing = preparations.some(item => item.state === 'preparing');
          const candidates = (overview.models ?? []).filter(item => item.ready && !registered.includes(item.model_id));
          const modelId = candidates.some(item => item.model_id === modelIds[row.id]) ? modelIds[row.id] : candidates[0]?.model_id;
          const previous = preparations.find(item => item.model_id === modelId);
          const mode = modes[row.id] ?? previous?.weight_mode ?? 'auto';
          const modelNames = new Map((overview.models ?? []).map(item => [item.model_id, item.name]));
          return <VStack key={row.id} gap={2}>
            <strong>{name} · {row.profile}</strong>
            <small>{row.image}</small>
            <p role="status">{tr(`state.${row.last_error && row.state === 'running' ? 'failed' : row.state}`)}</p>
            {row.last_error ? <p role="alert">{labelError(row.last_error)}</p> : null}
            {running ? <>
              {[...new Set([...registered, ...preparations.map(item => item.model_id)])].map(id => {
                const item = preparations.find(entry => entry.model_id === id);
                const ready = registered.includes(id);
                const percentage = item?.total_bytes ? Math.floor(100 * item.received_bytes / item.total_bytes) : null;
                return <VStack key={id} gap={1}>
                  <p role="status">{modelNames.get(id) ?? id}{ready ? ` · ${tr('registered')}` : item?.state === 'preparing' ? ` · ${tr(`phase.${item.phase}`)}` : ''}
                    {item?.weight_source ? ` · ${tr(`weight.${item.weight_source}`)}` : ''}
                    {item?.state === 'preparing' && percentage !== null ? ` · ${percentage}%` : ''}</p>
                  {!ready && item?.error ? <p role="alert">{labelError(item.error)}</p> : null}
                  {!preparing && (ready || item?.error) ? <HStack gap={2}>
                    <Button label={tr('removeModel')} isDisabled={!!busy} onClick={() => setRemove({ row, model: id })} />
                  </HStack> : null}
                </VStack>;
              })}
              {!preparing && modelId ? <HStack gap={2} wrap="wrap" vAlign="end">
                <Selector label={`${tr('model')} · ${name}`} value={modelId} options={candidates.map(item => ({
                  value: item.model_id, label: item.name,
                }))} onChange={value => setModelIds(current => ({ ...current, [row.id]: value }))} isDisabled={!!busy} />
                <Selector label={`${tr('weightMode')} · ${name}`} value={mode}
                  options={weights.map(value => ({ value, label: tr(`weight.${value}`) }))}
                  onChange={value => setModes(current => ({ ...current, [row.id]: value as WeightMode }))} isDisabled={!!busy} />
                <Button label={tr('prepare')} variant="primary" isDisabled={!!busy} onClick={() => control(row.id, 'prepare', modelId, mode)} />
              </HStack> : null}
              {!preparing && !modelId && !registered.length ? <p>{tr('sourceMissing')}</p> : null}
            </> : null}
            <HStack gap={2} wrap="wrap">
              {row.state === 'failed' || row.state === 'stopped' ? <Button label={tr('start')} isDisabled={!!busy} onClick={() => control(row.id, 'start')} /> : null}
              {row.state === 'running' || row.state === 'pending' ? <Button label={tr('stop')} isDisabled={!!busy || preparing} onClick={() => control(row.id, 'stop')} /> : null}
              {row.state !== 'deleting' && row.state !== 'stopping' ? <Button label={tr('remove')} variant="destructive" isDisabled={!!busy || preparing} onClick={() => setRemove({ row })} /> : null}
            </HStack>
          </VStack>;
        })}
      </> : null}
    </AppDialog>
    {remove ? <ConfirmDelete title={tr(remove.model ? 'removeModel' : 'remove')}
      description={`${remove.row.node_name || remove.row.target_id} · ${tr(remove.model ? 'removeModelDescription' : 'removeDescription')}`}
      confirmLabel={tr(remove.model ? 'removeModel' : 'remove')} busy={!!busy} onClose={() => setRemove(undefined)}
      onConfirm={() => control(remove.row.id, remove.model ? 'removeModel' : 'remove', remove.model)} /> : null}
  </>;
}
