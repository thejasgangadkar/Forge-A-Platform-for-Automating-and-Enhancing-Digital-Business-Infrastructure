'use client';

import React, { useEffect, useRef, useState, useCallback } from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/store';
import Icon from '@/components/Icon';
import Logo from '@/components/Logo';
import styles from './landing.module.css';

const STEPS = [
  {
    n: '01',
    title: 'Describe your business',
    body: 'Type it or say it out loud, in your own language. Or just paste the link to a site you already have.',
  },
  {
    n: '02',
    title: 'Forge builds it',
    body: 'A four-page website with real copy and real photography, plus AI agents grounded in your actual business details.',
  },
  {
    n: '03',
    title: 'Preview and refine',
    body: 'See it live, test your agent, then change anything by simply saying what you want different.',
  },
  {
    n: '04',
    title: 'Share it',
    body: 'One link your customers can open straight away. No login, no install, nothing to set up.',
  },
];

const CAPABILITIES = [
  {
    icon: 'globe',
    title: 'Multi-page websites',
    body: 'Home, About, Services and Contact, sharing one design system and real stock photography.',
  },
  {
    icon: 'bot',
    title: 'Agents that act',
    body: 'Seven agent types that book appointments, capture leads and escalate to you, not just answer questions.',
  },
  {
    icon: 'chat',
    title: 'Voice, in your language',
    body: 'Speak instead of typing. Thirty languages, including your language typed with English letters.',
  },
  {
    icon: 'layers',
    title: 'Grounded in your business',
    body: 'Retrieval memory per business, so nothing invents your hours, your prices or your address.',
  },
  {
    icon: 'spark',
    title: 'Analytics built in',
    body: 'Visits, conversations and captured leads, tracked from the moment you publish.',
  },
  {
    icon: 'external',
    title: 'Deploy instantly',
    body: 'A hosted page, a one-line embed for a site you already own, or download the code.',
  },
];

const LANG_SAMPLES = [
  { script: 'English', text: 'I need a website for my dental clinic' },
  { script: 'हिन्दी', text: 'मुझे अपने क्लिनिक के लिए वेबसाइट चाहिए' },
  { script: 'Romanized', text: 'mera dental clinic hai, website chahiye' },
  { script: 'ಕನ್ನಡ', text: 'ನನ್ನ ಕ್ಲಿನಿಕ್‌ಗೆ ವೆಬ್‌ಸೈಟ್ ಬೇಕು' },
  { script: 'தமிழ்', text: 'எனது கிளினிக்கிற்கு வலைத்தளம் வேண்டும்' },
];

export default function LandingPage() {
  const { user } = useAuth();
  const sectionRefs = useRef([]);
  const [visible, setVisible] = useState(new Set([0]));
  const [langIndex, setLangIndex] = useState(0);

  // Track which section is on screen: drives the reveals.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const idx = Number(entry.target.dataset.sectionIdx);
          if (entry.isIntersecting) {
            setVisible((prev) => new Set([...prev, idx]));
          }
        });
      },
      { threshold: 0.35 }
    );
    sectionRefs.current.forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, []);

  // Cycle the language samples, but stop for anyone who asked for reduced motion.
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;
    const id = setInterval(() => {
      setLangIndex((i) => (i + 1) % LANG_SAMPLES.length);
    }, 2600);
    return () => clearInterval(id);
  }, []);

  const scrollToSection = useCallback((idx) => {
    sectionRefs.current[idx]?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  const setSectionRef = useCallback((idx) => (el) => {
    sectionRefs.current[idx] = el;
  }, []);

  const shown = (idx) => visible.has(idx);
  const sample = LANG_SAMPLES[langIndex];

  return (
    <main className={styles.page}>
      {/* Liquid morphism background: fixed colour field behind all content. */}
      <div className="morph-field" aria-hidden="true">
        <div className="morph-blob" />
        <div className="morph-blob" />
        <div className="morph-blob" />
        <div className="morph-blob" />
      </div>

      <header>
        <nav className={styles.nav} aria-label="Main navigation">
          <Link href="/" className={styles.brand} aria-label="Forge home">
            <Logo size={26} />
          </Link>
          <div className={styles.navActions}>
            {user ? (
              <Link href="/dashboard" className={styles.btnPrimary}>Dashboard</Link>
            ) : (
              <>
                <Link href="/login" className={styles.btnGhost}>Sign in</Link>
                <Link href="/login?mode=signup" className={styles.btnPrimary}>Get started</Link>
              </>
            )}
          </div>
        </nav>
      </header>

      {/* 1 — HERO */}
      <section
        ref={setSectionRef(0)}
        data-section-idx={0}
        className={`${styles.section} ${styles.hero}`}
      >
        <div className={styles.heroInner}>
          <span className={styles.eyebrow}>Agentic AI for small business</span>
          <h1 className={styles.heroTitle}>
            Describe your business.<br />
            <span className={styles.heroAccent}>Get your whole online presence.</span>
          </h1>
          <p className={styles.heroLede}>
            Forge builds your website and your AI agents from one conversation. No code,
            no configuration, no separate tools to stitch together. Type it or say it,
            in your own language.
          </p>
          <div className={styles.heroCtas}>
            <Link href={user ? '/dashboard' : '/login?mode=signup'} className={styles.btnPrimaryLg}>
              Start building <Icon name="arrowUp" size={16} />
            </Link>
            <button type="button" className={styles.btnGhostLg} onClick={() => scrollToSection(2)}>
              See how it works
            </button>
          </div>
          <div className={styles.heroMeta}>
            <span>4-page website</span>
            <i />
            <span>7 agent types</span>
            <i />
            <span>30 languages</span>
            <i />
            <span>Voice built in</span>
          </div>
        </div>
      </section>

      {/* 2 — PROBLEM */}
      <section
        ref={setSectionRef(1)}
        data-section-idx={1}
        className={`${styles.section} ${shown(1) ? styles.in : ''}`}
      >
        <div className={styles.inner}>
          <span className={styles.eyebrow}>The problem</span>
          <h2 className={styles.h2}>Four tools that don&apos;t talk to each other</h2>
          <div className={styles.problemGrid}>
            {[
              { t: 'Website builder', d: 'Templates arrive empty. You write every word and find every image yourself.' },
              { t: 'Chatbot platform', d: 'A separate subscription that knows nothing about your site, and can only answer.' },
              { t: 'Automation tool', d: 'Webhooks and API keys, and it breaks silently when something changes.' },
              { t: 'A developer', d: 'For every small edit afterwards. Which most small businesses cannot afford.' },
            ].map((card, i) => (
              <div
                key={card.t}
                className={`${styles.problemCard} ${shown(1) ? styles.riseIn : ''}`}
                style={{ transitionDelay: `${i * 90}ms` }}
              >
                <h3>{card.t}</h3>
                <p>{card.d}</p>
              </div>
            ))}
          </div>
          <p className={styles.problemNote}>
            None of them share context. Connecting them takes exactly the technical skill
            a small business owner does not have.
          </p>
        </div>
      </section>

      {/* 3 — HOW IT WORKS */}
      <section
        ref={setSectionRef(2)}
        data-section-idx={2}
        className={`${styles.section} ${shown(2) ? styles.in : ''}`}
      >
        <div className={styles.inner}>
          <span className={styles.eyebrow}>How it works</span>
          <h2 className={styles.h2}>One conversation, start to finish</h2>
          <ol className={styles.steps}>
            {STEPS.map((step, i) => (
              <li
                key={step.n}
                className={`${styles.step} ${shown(2) ? styles.riseIn : ''}`}
                style={{ transitionDelay: `${i * 110}ms` }}
              >
                <span className={styles.stepNum}>{step.n}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* 4 — CAPABILITIES */}
      <section
        ref={setSectionRef(3)}
        data-section-idx={3}
        className={`${styles.section} ${shown(3) ? styles.in : ''}`}
      >
        <div className={styles.inner}>
          <span className={styles.eyebrow}>What you get</span>
          <h2 className={styles.h2}>Everything, from one description</h2>
          <div className={styles.capGrid}>
            {CAPABILITIES.map((cap, i) => (
              <div
                key={cap.title}
                className={`${styles.capCard} ${shown(3) ? styles.riseIn : ''}`}
                style={{ transitionDelay: `${i * 70}ms` }}
              >
                <span className={styles.capIcon}><Icon name={cap.icon} size={18} /></span>
                <h3>{cap.title}</h3>
                <p>{cap.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 5 — LANGUAGE */}
      <section
        ref={setSectionRef(4)}
        data-section-idx={4}
        className={`${styles.section} ${shown(4) ? styles.in : ''}`}
      >
        <div className={styles.inner}>
          <span className={styles.eyebrow}>Your language</span>
          <h2 className={styles.h2}>Say it however you say it</h2>
          <p className={styles.lede}>
            Thirty languages. Type in your own script, or type your language using English
            letters the way you already do on your phone. Forge understands both, and answers
            the same way.
          </p>
          <div className={styles.langCard} aria-live="polite">
            <div className={styles.langHead}>
              <span className={styles.dotLive} aria-hidden="true" />
              <span className={styles.langScript}>{sample.script}</span>
            </div>
            <p className={styles.langText} key={sample.text}>{sample.text}</p>
            <div className={styles.wave} aria-hidden="true">
              {Array.from({ length: 28 }).map((_, i) => (
                <i key={i} style={{ animationDelay: `${i * 0.045}s` }} />
              ))}
            </div>
            <span className={styles.langHint}>All five mean the same thing. All five work.</span>
          </div>
        </div>
      </section>

      {/* 6 — CTA + FOOTER */}
      <section
        ref={setSectionRef(5)}
        data-section-idx={5}
        className={`${styles.section} ${styles.ctaSection} ${shown(5) ? styles.in : ''}`}
      >
        <div className={styles.inner}>
          <h2 className={styles.ctaTitle}>
            Your business deserves to be found.
          </h2>
          <p className={styles.lede}>
            Describe it once. Forge handles the rest.
          </p>
          <Link href={user ? '/dashboard' : '/login?mode=signup'} className={styles.btnPrimaryLg}>
            Start building <Icon name="arrowUp" size={16} />
          </Link>
        </div>
        <footer className={styles.footer}>
          <span>Forge — websites and AI agents for small business</span>
          <span>B.M.S. College of Engineering, Bengaluru</span>
        </footer>
      </section>
    </main>
  );
}
