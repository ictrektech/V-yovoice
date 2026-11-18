import { HStack, VStack } from '@astryxdesign/core/Layout';
import { Button } from '@astryxdesign/core/Button';
import { useEffect, useState } from 'react';
import { useTranslator } from '@astryxdesign/core/i18n';
import { call } from '../../shared/lib/client';
import type { Draft, ModelPackage, State, UiLocale } from '../../shared/workbench';
import { useSharedModelInventory } from '../../shared/lib/model-inventory';
import { uiLocales } from '../../shared/i18n/locale';
import { Selector } from '../../shared/selector';
import { SettingsGroup, SettingsRow } from '../../shared/ui/settings-group';
import { ModelGroups } from './model-list';
import { setVosLocalePreference, vosLocalePreference, type VosLocalePreference } from '../../shared/lib/vos-locale';
import { vosFetch } from '../../shared/lib/vos';

// VOS 的模型及内核由共享服务管理，不显示桌面路径、HF 来源或内核下载安装。
export function VosSettings({ openModels, state, catalog, draft, run }: { openModels: () => void; state: State; catalog: ModelPackage[]; draft: Draft; run: (task: () => Promise<unknown>) => void }) {
  const t = useTranslator();
  const shared = useSharedModelInventory(true);
  const [localePreference, setLocalePreference] = useState(vosLocalePreference);
  const [idleSeconds, setIdleSeconds] = useState(120);
  const [dialogueMessage, setDialogueMessage] = useState('');
  useEffect(() => {
    void vosFetch('/api/v1/dialogue/settings').then(async response => {
      if (response.ok) setIdleSeconds((await response.json()).idle_unload_seconds);
    }).catch(() => undefined);
  }, []);
  async function saveDialogueSettings() {
    setDialogueMessage('');
    const response = await vosFetch('/api/v1/dialogue/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ idle_unload_seconds: idleSeconds }),
    });
    if (!response.ok) {
      setDialogueMessage(response.status === 403 ? t('@vvoice.dialogue.adminOnly') : t('@vvoice.dialogue.saveFailed'));
      return;
    }
    setIdleSeconds((await response.json()).idle_unload_seconds);
    setDialogueMessage(t('@vvoice.dialogue.saved'));
  }
  return <VStack className="settings-page" gap={6} style={{ overflowY: 'auto', overscrollBehavior: 'contain' }} data-testid="vos-settings">
    <header><h1>{t('@yovoice.settings.title')}</h1></header>
    <SettingsGroup title={t('@yovoice.settings.preferences')}>
      <SettingsRow label={t('@yovoice.settings.uiLocale')}>
        <Selector label={t('@yovoice.settings.uiLocale')} value={localePreference} options={[{ value: 'auto', label: t('@vvoice.locale.auto') }, ...uiLocales.map(locale => ({ value: locale.id, label: locale.name }))]}
          onChange={value => {
            setVosLocalePreference(value as VosLocalePreference); setLocalePreference(value as VosLocalePreference);
            if (value !== 'auto') run(() => call('preferences.save', { uiLocale: value as UiLocale }));
          }} />
      </SettingsRow>
      <SettingsRow label="ModelScope · V-Scheduler" hint={t('@vvoice.models.sharedHint')}>
        <Button data-testid="settings-open-models" variant="ghost" label={t('@vvoice.nav.models')} onClick={openModels} />
      </SettingsRow>
      <SettingsRow label="audio.cpp" hint={state.runtimeVersion ?? ''}>
        <p>{t('@vvoice.runtime.updates')}</p>
      </SettingsRow>
      <SettingsRow label={t('@vvoice.dialogue.idleSetting')} hint={t('@vvoice.dialogue.idleSettingHint')}>
        <VStack gap={2}>
          <HStack gap={2} vAlign="center">
            <input className="dialogue-idle-input" type="number" min={0} max={600} step={10} value={idleSeconds} onChange={event => setIdleSeconds(Number(event.target.value))} aria-label={t('@vvoice.dialogue.idleSetting')} />
            <Button size="sm" label={t('@vvoice.dialogue.save')} onClick={() => void saveDialogueSettings()} />
          </HStack>
          {dialogueMessage ? <small role="status">{dialogueMessage}</small> : null}
        </VStack>
      </SettingsRow>
    </SettingsGroup>
    <ModelGroups shared={shared.models} models={catalog} state={state} draft={draft} run={run} />
    <p>{t('@yovoice.settings.licenseBlurb')} <a href="./model-license.txt" target="_blank" rel="noreferrer">{t('@yovoice.settings.licenseButton')}</a></p>
  </VStack>;
}
