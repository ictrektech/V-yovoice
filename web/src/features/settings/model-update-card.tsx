import { useState } from 'react';
import { Button } from '@astryxdesign/core/Button';
import { HStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { Download, X } from 'lucide-react';
import { readLocal, writeLocal } from '../../shared/lib/local-store';
import { modelUpdateAvailable, type ModelPackage, type State } from '../../shared/workbench';

const dismissedKey = 'yovoice-model-update-dismissed';

export function ModelUpdateSidebarCard({ state, catalog, revision, openSettings }: { state: State; catalog: ModelPackage[]; revision: string; openSettings: (modelId: string) => void }) {
  const t = useTranslator();
  const [dismissedRevision, setDismissedRevision] = useState(() => readLocal(dismissedKey));
  const updates = catalog.filter(model => modelUpdateAvailable(state, model));
  if (!updates.length || dismissedRevision === revision) return null;
  const dismiss = () => {
    writeLocal(dismissedKey, revision);
    setDismissedRevision(revision);
  };
  return <HStack className="model-update-notice" gap={0} vAlign="center" data-testid="model-update-notice">
    <Button variant="ghost" className="model-update-action grow" icon={<Download size={18} />} label={t('@yovoice.settings.updateNotice', { count: updates.length })} onClick={() => openSettings(updates[0].id)} />
    <Button variant="ghost" size="sm" isIconOnly className="model-update-dismiss" icon={<X size={14} />} label={t('@yovoice.action.closeNotice')} onClick={dismiss} />
  </HStack>;
}
