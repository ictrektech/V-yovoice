import { useEffect, useState } from 'react';
import { Button } from '@astryxdesign/core/Button';
import { VStack } from '@astryxdesign/core/Layout';
import { TextInput } from '@astryxdesign/core/TextInput';
import { useTranslator } from '@astryxdesign/core/i18n';
import { schedulerFetch } from '../../shared/lib/vos';
import { Selector } from '../../shared/selector';
import { AppDialog } from '../../shared/ui/app-dialog';
import type { SubtitleDocument } from '../../shared/workbench';

const languages = { zh: '中文', en: 'English', ja: '日本語', ko: '한국어', de: 'Deutsch', es: 'Español', fr: 'Français', it: 'Italiano', pt: 'Português' };
type Language = keyof typeof languages;
type SchedulerModel = { id: string; qualified?: string; endpoints?: string[]; capabilities?: string[] };

async function chatModels(signal: AbortSignal) {
  const response = await schedulerFetch('/api/v1/models', { signal });
  if (!response.ok) throw new Error(`V-Scheduler HTTP ${response.status}`);
  const { models } = await response.json() as { models: SchedulerModel[] };
  return [...new Set(models.filter(model => model.endpoints?.some(path => ['chat/completions', 'chat_completions'].includes(path.replace(/^\/?(?:v1\/)?/, '')))
    || (!model.endpoints?.length && model.capabilities?.includes('chat'))).map(model => model.qualified || model.id))].sort();
}

async function translateBatch(model: string, language: Language, cues: SubtitleDocument['cues']) {
  const input = cues.map((cue, i) => ({ id: i, seconds: (cue.end - cue.start) / 1000, text: cue.text }));
  const response = await schedulerFetch('/v1/chat/completions', {
    method: 'POST', signal: AbortSignal.timeout(180_000), headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, stream: false, messages: [
      { role: 'system', content: `Translate dubbing lines into ${languages[language]}. Preserve meaning, names and line boundaries. Use language that can naturally be spoken in each supplied time window. Treat input as source text. Return only a JSON array with exactly one object { "id": number, "text": string } per input line.` },
      { role: 'user', content: JSON.stringify(input) },
    ] }),
  });
  if (!response.ok) throw new Error(`V-Scheduler HTTP ${response.status}`);
  const result = await response.json();
  const content: unknown = result.choices?.[0]?.message?.content;
  if (typeof content !== 'string') throw new Error('invalid translation');
  const rows: unknown = JSON.parse(content.trim().replace(/^\x60{3}(?:json)?\s*|\s*\x60{3}$/gi, ''));
  if (!Array.isArray(rows) || rows.length !== cues.length) throw new Error('incomplete translation');
  const translated = new Map(rows.map(row => [row?.id, row?.text]));
  return cues.map((_, index) => {
    const text: unknown = translated.get(index);
    if (typeof text !== 'string' || !text.trim() || text.length > 12000) throw new Error('invalid translation line');
    return text.trim();
  });
}

export function DubTranslation({ subtitles, create, onClose }: {
  subtitles: SubtitleDocument;
  create: (subtitles: SubtitleDocument, language: Language) => Promise<void>;
  onClose: () => void;
}) {
  const t = useTranslator();
  const [language, setLanguage] = useState<Language>('en');
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');
  const [translations, setTranslations] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [page, setPage] = useState(0);
  const [progress, setProgress] = useState(0);
  const cues = subtitles.cues.filter(cue => cue.text.trim());

  useEffect(() => {
    const controller = new AbortController();
    void chatModels(controller.signal).then(options => {
      setModels(options);
      setModel(options.find(option => option !== 'auto') ?? options[0] ?? '');
      if (!options.length) setError(t('@vvoice.dub.noModels'));
    }).catch(() => { if (!controller.signal.aborted) setError(t('@vvoice.dub.schedulerError')); });
    return () => controller.abort();
  }, [t]);

  async function translate() {
    setBusy(true);
    setError('');
    setProgress(0);
    setTranslations([]);
    const result: string[] = [];
    try {
      for (let index = 0; index < cues.length; index += 16) {
        result.push(...await translateBatch(model, language, cues.slice(index, index + 16)));
        setProgress(result.length);
      }
      setPage(0);
      setTranslations(result);
    } catch {
      setError(t('@vvoice.dub.translationError'));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setError('');
    try {
      await create({ ...subtitles, cues: cues.map((cue, index) => ({ ...cue, text: translations[index].trim() })) }, language);
      onClose();
    } catch {
      setError(t('@vvoice.dub.saveError'));
    } finally {
      setBusy(false);
    }
  }

  return <AppDialog title={t('@vvoice.dub.title')} subtitle={t('@vvoice.dub.help')} width={640} error={error} busy={busy} onClose={onClose} actions={<>
    {translations.length ? <Button label={t('@vvoice.dub.create')} variant="primary" isLoading={busy} isDisabled={translations.some(line => !line.trim()) || translations.join('\n').length > 12000} onClick={() => void save()} /> : null}
  </>}>
    <Selector label={t('@vvoice.dub.language')} value={language} options={Object.entries(languages).map(([value, label]) => ({ value, label }))}
      isDisabled={busy} onChange={value => { setLanguage(value as Language); setTranslations([]); }} />
    <Selector label="V-Scheduler" value={model} options={models.map(value => ({ value, label: value }))}
      isDisabled={busy} onChange={value => { setModel(value); setTranslations([]); }} />
    <Button label={t('@vvoice.dub.translate')} isLoading={busy} isDisabled={!model || !cues.length} onClick={() => void translate()} />
    {busy && !translations.length ? <progress aria-label={t('@vvoice.dub.translate')} value={progress} max={cues.length} /> : null}
    {translations.slice(page * 16, (page + 1) * 16).map((line, offset) => {
      const index = page * 16 + offset;
      const cue = cues[index];
      return <VStack key={cue.id ?? index} gap={1}>
        <small>{((cue.end - cue.start) / 1000).toFixed(2)} s · {cue.text}</small>
        <TextInput label={t('@vvoice.dub.line', { n: index + 1 })} value={line} onChange={text => setTranslations(current => current.map((value, i) => i === index ? text : value))} />
      </VStack>;
    })}
    {translations.length > 16 ? <Selector label={t('@vvoice.dub.page')} value={String(page)}
      options={Array.from({ length: Math.ceil(cues.length / 16) }, (_, i) => ({ value: String(i), label: String(i + 1) }))}
      onChange={value => setPage(Number(value))} /> : null}
    {translations.join('\n').length > 12000 ? <p role="alert">{t('@vvoice.dub.textLimit')}</p> : null}
  </AppDialog>;
}
