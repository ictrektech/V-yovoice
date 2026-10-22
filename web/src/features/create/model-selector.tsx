import { useState } from 'react';
import { Button } from '@astryxdesign/core/Button';
import { HStack, VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { Download, Pause } from 'lucide-react';
import { Selector, SelectorOption } from '../../shared/selector';
import { call, isDesktop } from '../../shared/lib/client';
import { noticeMessage } from '../../shared/lib/call-error';
import { formatNotice } from '../../shared/i18n/format';
import { useSharedModelInventory } from '../../shared/lib/model-inventory';
import { isVos } from '../../shared/lib/vos';
import { formatSize, type ModelPackage, type State } from '../../shared/workbench';

// 可选模型：只列已下载的，当前选中但未下载的也保留；一个都没下载时列出全部，方便首次选择后去下载。
export function modelChoices(models: ModelPackage[], state: State, current: string) {
  const installed = models.filter(model => state.models.some(item => item.id === model.id));
  if (!installed.length) return models;
  const selected = models.find(model => model.id === current);
  return selected && !installed.includes(selected) ? [selected, ...installed] : installed;
}

// 配音、音乐、编曲共用的模型选择器：同样的筛选、同样的“已安装 / 未下载 · 大小”说明，末尾是“管理模型…”。
// 选中未下载的模型时直接给出下载入口，避免跳到设置页再找模型。
export function ModelSelector({ label, models, state, value, isDisabled, manage, onChange, name = model => `${model.name} · ${model.precision}` }: {
  label: string; models: ModelPackage[]; state: State; value: string; isDisabled?: boolean;
  manage?: () => void; onChange: (modelId: string) => void; name?: (model: ModelPackage) => string;
}) {
  const t = useTranslator();
  const model = models.find(item => item.id === value);
  const installed = state.models.some(item => item.id === value);
  const { models: shared } = useSharedModelInventory(!!model && !installed);
  const hub = shared[value];
  const activity = state.modelActivity?.kind === 'download' && state.modelActivity.modelId === value ? state.modelActivity : null;
  const ready = installed || hub?.status === 'ready';
  const downloading = hub ? hub.status === 'downloading' : activity?.status === 'running';
  const verifying = hub?.status === 'verifying';
  const failed = hub ? hub.status === 'failed' : activity?.status === 'failed';
  const received = hub?.downloaded_bytes ?? activity?.received ?? 0;
  const total = hub?.total_bytes || activity?.total || model?.size || 0;
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function download(method: 'model.download' | 'model.cancel') {
    setBusy(true); setError('');
    try { await call(method, { id: value }); }
    catch (reason) {
      const message = noticeMessage(reason);
      // VOS 只有模型管理员可以下载；其余错误保留原始原因。
      setError(/administrator/i.test(message) ? t('@vvoice.music.adminRequired') : formatNotice(t, message));
    }
    finally { setBusy(false); }
  }
  const options = modelChoices(models, state, value).map(model => ({
    value: model.id, label: name(model),
    description: state.models.some(item => item.id === model.id) ? t('@yovoice.create.modelInstalled') : formatSize(model.size),
  }));
  return <VStack gap={2}>
    <Selector label={label} isLabelHidden width="100%" className="model-selector" value={value} isDisabled={isDisabled}
      renderOption={option => <SelectorOption label={option.label} description={option.description} layout="inline" />} renderValue={option => option.label}
      options={[...options, ...(manage ? [{ value: 'manage', label: t('@yovoice.create.manageModels') }] : [])]}
      onChange={modelId => { if (modelId === 'manage') manage?.(); else onChange(modelId); }} />
    {model && !ready && (isDesktop || isVos) ? <VStack gap={2} data-testid="model-download-inline">
      <HStack gap={2} vAlign="center" wrap="wrap">
        <small className="grow" role={downloading ? 'status' : undefined}>
          {downloading ? `${t('@yovoice.settings.download.running')} · ${formatSize(received)} / ${formatSize(total)}`
            : verifying ? t('@yovoice.settings.download.verifying')
              : failed ? t('@yovoice.settings.download.failed')
                : `${t('@yovoice.create.modelMissing')} · ${formatSize(total)}`}
        </small>
        {downloading ? <Button size="sm" variant="ghost" label={t('@yovoice.action.pause')} icon={<Pause size={14} />} isLoading={busy} onClick={() => void download('model.cancel')} />
          : <Button size="sm" variant="ghost" label={failed ? t('@yovoice.settings.resumeDownload') : t('@yovoice.settings.downloadModel')} icon={<Download size={14} />} isLoading={busy} isDisabled={verifying} onClick={() => void download('model.download')} />}
      </HStack>
      {downloading || verifying ? <progress aria-label={t('@yovoice.settings.downloadModel')} value={verifying ? undefined : received} max={total || 1} /> : null}
      {failed && hub?.error ? <small role="alert">{hub.error}</small> : null}
      {error ? <small role="alert">{error}</small> : null}
    </VStack> : null}
  </VStack>;
}
