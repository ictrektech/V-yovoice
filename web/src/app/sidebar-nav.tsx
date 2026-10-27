import { useState, type ReactNode } from 'react';
import { ResizeHandle, type ResizableProps } from '@astryxdesign/core/Resizable';
import { Button } from '@astryxdesign/core/Button';
import { HStack, VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { AudioLines, BookOpen, ChevronRight, Fingerprint, Library, ListFilter, Mic, Music, Pencil, ScanText, Settings2, Speech, Trash2 } from 'lucide-react';
import { projectKind, type Draft, type State } from '../shared/workbench';
import { overflowTitle } from '../shared/ui/overflow-title';
import { UpdateSidebarCard } from '../features/update/update-notice';
import { isVos } from '../shared/lib/vos';

// 侧栏：新建入口、作品类型、声音库、最近作品、创作助手与设置。
export function SidebarNav(props: {
  page: string;
  setPage: (id: string) => void;
  newDraft: ReactNode;
  state: State;
  draft: Draft;
  selectDraft: (item: Draft) => void;
  removeDraft: (item: Draft) => void;
  resizable: ResizableProps;
}) {
  const t = useTranslator();
  const { page, setPage, newDraft, state, draft, selectDraft, removeDraft, resizable } = props;
  const [recentOpen, setRecentOpen] = useState(() => localStorage.getItem('yovoice-recent-open') !== 'false');
  const [modelsOpen, setModelsOpen] = useState(true);
  const modelsActive = page === 'models' || page === 'models-creative';
  const projectActive = page === 'create' || page === 'history';
  return <VStack as="nav" className="sidebar" aria-label={t('@yovoice.nav.main')} gap={6} data-testid="sidebar" style={isVos ? { overflowY: 'auto' } : undefined}>
    {newDraft}
    <VStack className="sidebar-destinations" gap={2}>
      {isVos ? <VStack gap={1}>
        <Button data-testid="nav-models" label={t('@vvoice.nav.models')} variant="ghost" icon={<Library />} className="nav-item" aria-expanded={modelsOpen} aria-controls="model-navigation" endContent={<ChevronRight style={{ transform: modelsOpen ? 'rotate(90deg)' : undefined }} />} onClick={() => { setModelsOpen(!modelsOpen); if (!modelsActive) { setModelsOpen(true); setPage('models'); } }} />
        {modelsOpen ? <VStack id="model-navigation" gap={1} style={{ paddingInlineStart: 'var(--spacing-4)' }}>
          {([['models', 'speechNav', Speech], ['models-creative', 'creativeNav', Music]] as const).map(([destination, label, Icon]) => <Button key={destination} data-testid={`nav-${destination}-category`} label={t(`@vvoice.models.${label}`)} variant="ghost" icon={<Icon />} className={`nav-item ${page === destination ? 'selected' : ''}`} aria-current={page === destination ? 'page' : undefined} onClick={() => setPage(destination)} />)}
        </VStack> : null}
      </VStack> : null}
      {isVos ? ([['asr', ScanText], ['tts', Speech], ['speaker', Fingerprint], ['hotwords', ListFilter]] as const).map(([destination, Icon]) => <Button key={destination} data-testid={`nav-${destination}`} label={t(`@vvoice.nav.${destination}`)} variant="ghost" icon={<Icon />} className={`nav-item ${page === destination ? 'selected' : ''}`} aria-current={page === destination ? 'page' : undefined} onClick={() => setPage(destination)} />) : null}
      {(['text', 'story', 'music'] as const).map(kind => {
        // 编曲生成并入音乐生成：两类作品都高亮「音乐生成」。
        const group = (k: string) => k === 'score' ? 'music' : k;
        const selected = group(page) === kind || (projectActive && group(projectKind(draft)) === kind);
        return <Button key={kind} data-testid={`nav-${kind}`} label={t(`@yovoice.project.${kind}`)} variant="ghost" icon={kind === 'text' ? <Mic /> : kind === 'story' ? <Pencil /> : <Music />} className={`nav-item ${selected ? 'selected' : ''}`} aria-current={selected ? 'page' : undefined} onClick={() => setPage(kind)} />;
      })}
      <Button data-testid="nav-characters" label={t('@yovoice.nav.characters')} variant="ghost" icon={<AudioLines />} className={`nav-item ${page === 'characters' || page === 'voices' ? 'selected' : ''}`} aria-current={page === 'characters' || page === 'voices' ? 'page' : undefined} onClick={() => setPage('characters')} />
      {isVos ? <Button data-testid="nav-api-docs" label={t('@vvoice.nav.api')} variant="ghost" icon={<BookOpen />} className={`nav-item ${page === 'api-docs' ? 'selected' : ''}`} aria-current={page === 'api-docs' ? 'page' : undefined} onClick={() => setPage('api-docs')} /> : null}
    </VStack>
    <details className="recent-projects" open={recentOpen}>
      <summary onClick={event => { event.preventDefault(); const open = !recentOpen; setRecentOpen(open); localStorage.setItem('yovoice-recent-open', String(open)); }}><ChevronRight aria-hidden />{t('@yovoice.nav.recent')}</summary>
      <VStack className="project-list" gap={1}>{[...state.drafts].sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? '')).slice(0, 5).map(item => <HStack key={item.id} className={`project-row ${item.id === draft.id && page === 'create' ? 'current' : ''}`} gap={0}>
        <Button label={item.id === draft.id ? draft.title : item.title} variant="ghost" size="sm" className="project-link grow" onPointerEnter={overflowTitle} aria-current={item.id === draft.id && page === 'create' ? 'page' : undefined} onClick={() => selectDraft(item)} />
        <Button className="project-quick-delete" label={t('@yovoice.nav.deleteProject', { title: item.id === draft.id ? draft.title : item.title })} icon={<Trash2 />} isIconOnly size="sm" variant="ghost" onClick={() => removeDraft(item.id === draft.id ? draft : item)} />
      </HStack>)}</VStack>
    </details>
    <VStack className="sidebar-bottom" gap={3}><UpdateSidebarCard />
      <Button data-testid="nav-settings" label={t('@yovoice.nav.settings')} icon={<Settings2 size={18} />} variant="ghost" className={`nav-item ${page === 'settings' ? 'selected' : ''}`} onClick={() => setPage('settings')} /></VStack>
    <ResizeHandle label={t('@yovoice.nav.resize')} direction="horizontal" position="overlay" pillPlacement="center" resizable={resizable} isAlwaysVisible={false} />
  </VStack>;
}
