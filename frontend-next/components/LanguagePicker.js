'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import styles from './LanguagePicker.module.css';

const STORAGE_KEY = 'forge.language';

// Shown before the network call resolves, and kept as the fallback if it fails.
// A picker that renders empty would look broken, and English is the safe default.
const FALLBACK = [
  { code: 'en', name: 'English', native_name: 'English', locale: 'en-US' },
];

/**
 * useLanguages — loads the supported language list once and remembers the
 * user's choice across visits.
 *
 * The chosen language drives three things at once: the language the assistant
 * replies in, the language of the generated website copy, and the BCP-47 locale
 * the browser uses for speech recognition and synthesis. Keeping them in one
 * place is what stops a user speaking Kannada and being answered in English.
 */
export function useLanguages() {
  const [languages, setLanguages] = useState(FALLBACK);
  const [code, setCode] = useState('en');
  const [loaded, setLoaded] = useState(false);

  // Restore the saved preference before fetching, so the correct value is shown
  // immediately on a repeat visit instead of flashing English first.
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) setCode(saved);
    } catch {
      /* private browsing or storage disabled: the default is fine */
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.languages()
      .then((r) => {
        if (cancelled || !r?.languages?.length) return;
        setLanguages(r.languages);
      })
      .catch(() => {
        /* keep FALLBACK: the app must stay usable without this list */
      })
      .finally(() => { if (!cancelled) setLoaded(true); });
    return () => { cancelled = true; };
  }, []);

  const choose = (next) => {
    setCode(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore: an unsaved preference is not worth failing over */
    }
  };

  const current = languages.find((l) => l.code === code) || FALLBACK[0];

  return { languages, code, setCode: choose, current, locale: current.locale, loaded };
}

/**
 * LanguagePicker — a native <select>, deliberately.
 *
 * A custom dropdown would need its own keyboard handling, focus trapping and
 * screen-reader wiring to match what the browser already gives us for free, and
 * on mobile the native control is a better experience than any recreation.
 */
export default function LanguagePicker({
  languages,
  code,
  onChange,
  disabled = false,
  compact = false,
  label = 'Language',
}) {
  return (
    <label className={`${styles.wrap} ${compact ? styles.compact : ''}`}>
      <span className={styles.srOnly}>{label}</span>
      <GlobeIcon />
      <select
        className={styles.select}
        value={code}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
      >
        {languages.map((l) => (
          <option key={l.code} value={l.code}>
            {/* Native name first: someone looking for their own language scans
                for how it is written in that language, not its English name. */}
            {l.native_name === l.name ? l.name : `${l.native_name} · ${l.name}`}
          </option>
        ))}
      </select>
    </label>
  );
}

function GlobeIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="10" />
      <line x1="2" y1="12" x2="22" y2="12" />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </svg>
  );
}
