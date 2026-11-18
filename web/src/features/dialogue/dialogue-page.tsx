import { useEffect, useRef, useState } from 'react';
import { Button } from '@astryxdesign/core/Button';
import { HStack, VStack } from '@astryxdesign/core/Layout';
import { useTranslator } from '@astryxdesign/core/i18n';
import { Mic, PhoneOff, Radio } from 'lucide-react';
import { Selector } from '../../shared/selector';
import { isVos, vosBase, vosFetch } from '../../shared/lib/vos';
import { inspectMicrophone, microphoneError, type MicrophoneState } from './microphone';

type Status = {
  supported: boolean;
  model_installed: boolean;
  state: string;
  busy: boolean;
  idle_unload_seconds: number;
};

type Phase = 'idle' | 'loading' | 'active' | 'ending' | 'error';

const languages = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
];
function downsample(input: Float32Array, inputRate: number, outputRate = 24000): Int16Array {
  if (inputRate === outputRate) {
    const exact = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) exact[i] = Math.max(-32768, Math.min(32767, Math.round(input[i] * 32767)));
    return exact;
  }
  const length = Math.max(1, Math.round(input.length * outputRate / inputRate));
  const output = new Int16Array(length);
  const ratio = inputRate / outputRate;
  for (let i = 0; i < length; i++) {
    const position = i * ratio;
    const left = Math.floor(position);
    const right = Math.min(input.length - 1, left + 1);
    const value = input[left] + (input[right] - input[left]) * (position - left);
    output[i] = Math.max(-32768, Math.min(32767, Math.round(value * 32767)));
  }
  return output;
}

export function DialoguePage() {
  const t = useTranslator();
  const personas = [
    { value: 'companion', label: t('@vvoice.dialogue.personaCompanion') },
    { value: 'study', label: t('@vvoice.dialogue.personaStudy') },
    { value: 'interview', label: t('@vvoice.dialogue.personaInterview') },
  ];
  const [status, setStatus] = useState<Status | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [language, setLanguage] = useState('zh');
  const [persona, setPersona] = useState('companion');
  const [error, setError] = useState('');
  const [text, setText] = useState('');
  const [microphone, setMicrophone] = useState<MicrophoneState>('checking');
  const socket = useRef<WebSocket | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const micContext = useRef<AudioContext | null>(null);
  const playbackContext = useRef<AudioContext | null>(null);
  const playAt = useRef(0);
  const microphoneFailed = useRef(false);
  const sendAudio = useRef(false);
  const active = phase === 'active' || phase === 'ending';
  const busy = active || phase === 'loading';

  async function refresh() {
    try {
      const response = await vosFetch('/api/v1/dialogue/status');
      if (!response.ok) throw new Error(await response.text());
      setStatus(await response.json());
    } catch (value) {
      setError(String(value));
    }
  }

  useEffect(() => {
    if (isVos) void refresh();
    const detect = () => { void inspectMicrophone().then(setMicrophone); };
    detect();
    const media = navigator.mediaDevices;
    media?.addEventListener?.('devicechange', detect);
    window.addEventListener('focus', detect);
    return () => {
      media?.removeEventListener?.('devicechange', detect);
      window.removeEventListener('focus', detect);
      socket.current?.close();
      socket.current = null;
      stopAudio();
    };
  }, []);

  function stopAudio() {
    sendAudio.current = false;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    void micContext.current?.close();
    micContext.current = null;
    void playbackContext.current?.close();
    playbackContext.current = null;
    playAt.current = 0;
  }

  function playPcm(raw: ArrayBuffer) {
    const samples = new Int16Array(raw);
    if (!samples.length) return;
    const context = playbackContext.current ?? new AudioContext({ sampleRate: 24000 });
    playbackContext.current = context;
    const buffer = context.createBuffer(1, samples.length, 24000);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 32768;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const at = Math.max(context.currentTime, playAt.current);
    source.start(at);
    playAt.current = at + buffer.duration;
  }

  async function startMicrophone() {
    const media = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    let context: AudioContext | null = null;
    try {
      context = new AudioContext();
      await context.resume();
      const source = context.createMediaStreamSource(media);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const silent = context.createGain();
      silent.gain.value = 0;
      processor.onaudioprocess = event => {
        if (!sendAudio.current || socket.current?.readyState !== WebSocket.OPEN) return;
        const pcm = downsample(event.inputBuffer.getChannelData(0), context!.sampleRate);
        socket.current.send(pcm.buffer);
      };
      source.connect(processor);
      processor.connect(silent);
      silent.connect(context.destination);
      stream.current = media;
      micContext.current = context;
    } catch (value) {
      media.getTracks().forEach(track => track.stop());
      void context?.close();
      throw value;
    }
  }

  async function start() {
    if (!isVos || busy) return;
    setError('');
    setText('');
    microphoneFailed.current = false;
    setPhase('loading');
    stopAudio();
    try {
      await startMicrophone();
    } catch (value) {
      microphoneFailed.current = true;
      setError(microphoneError(t, value));
      setPhase('error');
      stopAudio();
      return;
    }
    try {
      const ticketResponse = await vosFetch('/api/v1/dialogue/tickets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language, persona_id: persona, max_seconds: 180 }),
      });
      if (!ticketResponse.ok) throw new Error(await ticketResponse.text());
      const ticket = await ticketResponse.json();
      const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${scheme}://${location.host}${vosBase}${ticket.ws_path}?ticket=${encodeURIComponent(ticket.ticket)}`);
      ws.binaryType = 'arraybuffer';
      socket.current = ws;
      ws.onopen = () => ws.send(JSON.stringify({ type: 'start', protocol: 1 }));
      ws.onmessage = event => {
        if (typeof event.data !== 'string') {
          playPcm(event.data);
          return;
        }
        const message = JSON.parse(event.data);
        if (message.type === 'started') {
          setPhase('active');
          sendAudio.current = true;
        } else if (message.type === 'text') {
          setText(current => `${current}${message.text}`.slice(-4000));
        } else if (message.type === 'end') {
          setPhase(microphoneFailed.current ? 'error' : 'idle');
          stopAudio();
          void refresh();
        } else if (message.type === 'error') {
          setError(message.message || message.code || 'Dialogue failed');
          setPhase('error');
          stopAudio();
          void refresh();
        }
      };
      ws.onerror = () => {
        setError(t('@vvoice.dialogue.connectionFailed'));
        setPhase('error');
        stopAudio();
      };
      ws.onclose = () => {
        socket.current = null;
        stopAudio();
        setPhase(current => current === 'error' ? current : 'idle');
      };
    } catch (value) {
      setError(String(value));
      setPhase('error');
      stopAudio();
    }
  }

  async function hangUp() {
    if (!socket.current || socket.current.readyState !== WebSocket.OPEN) return;
    setPhase(current => current === 'error' ? current : 'ending');
    sendAudio.current = false;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    socket.current.send(JSON.stringify({ type: 'hang_up' }));
  }

  const unavailable = !isVos || microphone !== 'available' || !status?.supported || !status?.model_installed;
  const stateMessage = status?.busy && !active
    ? t('@vvoice.dialogue.busy')
    : !status?.model_installed
      ? t('@vvoice.dialogue.modelMissing')
      : !status?.supported
        ? t('@vvoice.dialogue.unsupported')
        : microphone === 'missing'
          ? t('@yovoice.error.micNotFound')
          : microphone === 'unsupported'
            ? t('@yovoice.error.micDeniedBrowser')
            : phase === 'loading'
              ? t('@vvoice.dialogue.loading')
              : phase === 'ending'
                ? t('@vvoice.dialogue.ending')
                : t('@vvoice.dialogue.ready');

  return <VStack className="dialogue-page" gap={6}>
    <HStack hAlign="between" vAlign="center" wrap="wrap" gap={3}>
      <VStack gap={1}>
        <HStack gap={2} vAlign="center"><Radio size={20} aria-hidden /><h1>{t('@vvoice.dialogue.title')}</h1></HStack>
        <p>{t('@vvoice.dialogue.description')}</p>
      </VStack>
      <Button data-testid="dialogue-start" label={t('@vvoice.dialogue.start')} icon={<Mic size={18} />} variant="primary" isDisabled={unavailable || busy} onClick={() => void start()} />
    </HStack>
    <HStack gap={4} wrap="wrap" vAlign="end">
      <Selector label={t('@vvoice.dialogue.language')} value={language} options={languages} onChange={setLanguage} isDisabled={busy} />
      <Selector label={t('@vvoice.dialogue.persona')} value={persona} options={personas} onChange={setPersona} isDisabled={busy} />
    </HStack>
    <VStack className="dialogue-panel" gap={3} role={error ? 'alert' : 'status'}>
      <HStack hAlign="between" vAlign="center" gap={3}>
        <strong className={error ? 'dialogue-error' : undefined}>{error || stateMessage}</strong>
        {active ? <Button data-testid="dialogue-hangup" label={t('@vvoice.dialogue.hangup')} icon={<PhoneOff size={18} />} variant="destructive" onClick={() => void hangUp()} /> : null}
      </HStack>
      {text ? <p className="dialogue-transcript" aria-live="polite">{text}</p> : <p className="dialogue-hint">{t('@vvoice.dialogue.hint')}</p>}
    </VStack>
  </VStack>;
}
