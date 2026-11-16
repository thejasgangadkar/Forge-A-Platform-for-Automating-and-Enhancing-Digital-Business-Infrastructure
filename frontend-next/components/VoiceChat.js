'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import styles from './VoiceChat.module.css';

/**
 * VoiceChat — browser-native speech-to-text and text-to-speech.
 *
 * Uses the Web Speech API, so voice costs nothing and needs no external service.
 *
 * Props:
 *   onTranscript(text) — called with the transcribed speech
 *   speakText          — text to read aloud; spoken once each time it changes
 *   autoSpeak          — when false, incoming speakText is ignored
 *   disabled           — disables the mic button
 *   locale             — BCP-47 tag ('hi-IN', 'kn-IN'). Sets the recognition
 *                        language AND picks a matching synthesis voice, so a
 *                        user can speak and be answered in their own language.
 */
export default function VoiceChat({
  onTranscript,
  speakText = '',
  autoSpeak = true,
  disabled = false,
  locale = 'en-US',
}) {
  const [state, setState] = useState('idle'); // idle | listening | speaking
  const [supported, setSupported] = useState({ stt: false, tts: false });
  const [voices, setVoices] = useState([]);
  const recognitionRef = useRef(null);
  const spokenRef = useRef('');

  // Feature detection must happen after mount: on the server there is no
  // window, and checking during render would break hydration.
  useEffect(() => {
    setSupported({
      stt: 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window,
      tts: 'speechSynthesis' in window,
    });
  }, []);

  // Voice list loading is asynchronous in most browsers: getVoices() usually
  // returns [] on the first call and only fills in once the engine is ready.
  // Without listening for voiceschanged, the first non-English reply would be
  // read by the default English voice, which is unintelligible.
  useEffect(() => {
    if (!supported.tts) return undefined;
    const synth = window.speechSynthesis;
    const load = () => setVoices(synth.getVoices() || []);
    load();
    synth.addEventListener?.('voiceschanged', load);
    return () => synth.removeEventListener?.('voiceschanged', load);
  }, [supported.tts]);

  const startListening = useCallback(() => {
    if (!supported.stt || disabled) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SR();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = locale || 'en-US';

    recognition.onstart = () => setState('listening');
    recognition.onend = () => setState((s) => (s === 'listening' ? 'idle' : s));
    recognition.onerror = () => setState('idle');
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      if (transcript && onTranscript) onTranscript(transcript);
      setState('idle');
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch {
      setState('idle');
    }
  }, [supported.stt, disabled, onTranscript, locale]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setState('idle');
  }, []);

  // Speak whenever a new reply arrives. This lives in an effect, not the render
  // body, so it fires once per distinct message instead of on every re-render.
  useEffect(() => {
    if (!autoSpeak || !supported.tts) return;
    const text = (speakText || '').trim();
    if (!text || text === spokenRef.current) return;

    spokenRef.current = text;
    const synth = window.speechSynthesis;
    synth.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = locale || 'en-US';
    // Prefer an exact locale match, then any voice for the same base language
    // ('hi-IN' -> any 'hi-*'). If the device has no voice for the language we
    // leave utterance.voice unset and let the browser do its best, rather than
    // forcing an English voice onto non-English text.
    const base = (locale || 'en').split('-')[0];
    const match = voices.find((v) => v.lang === locale)
      || voices.find((v) => (v.lang || '').split('-')[0] === base)
      || voices.find((v) => (v.lang || '').replace('_', '-') === locale);
    if (match) utterance.voice = match;
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.onstart = () => setState('speaking');
    utterance.onend = () => setState((s) => (s === 'speaking' ? 'idle' : s));
    utterance.onerror = () => setState((s) => (s === 'speaking' ? 'idle' : s));
    synth.speak(utterance);
  }, [speakText, autoSpeak, supported.tts, locale, voices]);

  // Never leave speech running after the component goes away.
  useEffect(() => () => {
    try {
      recognitionRef.current?.abort();
      window.speechSynthesis?.cancel();
    } catch {
      /* nothing useful to do during teardown */
    }
  }, []);

  const stopSpeaking = useCallback(() => {
    window.speechSynthesis?.cancel();
    setState('idle');
  }, []);

  // Without speech recognition there is nothing for this control to do.
  if (!supported.stt && !supported.tts) return null;

  const handleClick = () => {
    if (state === 'listening') stopListening();
    else if (state === 'speaking') stopSpeaking();
    else startListening();
  };

  const label =
    state === 'listening' ? 'Stop listening'
      : state === 'speaking' ? 'Stop speaking'
        : 'Start voice input';

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled && state === 'idle'}
      className={`${styles.mic} ${styles[state]}`}
      title={
        state === 'listening' ? 'Listening… click to stop'
          : state === 'speaking' ? 'Speaking… click to stop'
            : 'Click and speak'
      }
      aria-label={label}
      aria-pressed={state !== 'idle'}
    >
      {state === 'speaking' ? <SpeakerIcon /> : <MicIcon active={state === 'listening'} />}
    </button>
  );
}

function MicIcon({ active }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill={active ? 'currentColor' : 'none'}
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" fill="none" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function SpeakerIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
      <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
    </svg>
  );
}
