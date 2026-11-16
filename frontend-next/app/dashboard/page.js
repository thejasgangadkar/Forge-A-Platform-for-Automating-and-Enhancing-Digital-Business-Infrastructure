'use client';
import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '@/lib/api';
import Icon from '@/components/Icon';
import { LogoMark } from '@/components/Logo';
import styles from './chat.module.css';

const WELCOME = {
  role: 'assistant',
  content:
    "Tell me about the business — what it does, the services it offers, its opening hours — and I'll build the website and the AI agents from that. If a site already exists, paste the link and I'll read it first.",
};

const SUGGESTIONS = [
  'Build a website for my coffee roastery',
  'I need an AI receptionist for my dental clinic',
  'Here is my site: https://example.com — make it better',
  'Create a support agent + landing page for my SaaS',
];

export default function DashboardHome() {
  const router = useRouter();
  const [messages, setMessages] = useState([WELCOME]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [building, setBuilding] = useState(false);
  const [stage, setStage] = useState('');
  const [online, setOnline] = useState(null); // null = checking
  const endRef = useRef(null);

  // A static "Ready to build" label would be a lie whenever the backend is
  // down, so the indicator reflects an actual health call.
  useEffect(() => {
    let cancelled = false;
    api.health()
      .then(() => { if (!cancelled) setOnline(true); })
      .catch(() => { if (!cancelled) setOnline(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, busy, building]);

  const send = async (text) => {
    const content = (text ?? input).trim();
    if (!content || busy || building) return;
    const next = [...messages, { role: 'user', content }];
    setMessages(next);
    setInput('');
    setBusy(true);
    try {
      const history = next.filter((m) => m.role !== 'system').map((m) => ({ role: m.role, content: m.content }));
      const res = await api.chat(history);
      setBusy(false);

      if (res.reply) setMessages((m) => [...m, { role: 'assistant', content: res.reply }]);

      if (res.action === 'generate') {
        await build(res.summary || content, res.business_name, res.build_plan, res.scrape_ref);
      }
    } catch (e) {
      setBusy(false);
      setMessages((m) => [...m, { role: 'assistant', content: `That request failed: ${e.message}` }]);
    }
  };

  const build = async (summary, businessName, plan, scrapeRef) => {
    setBuilding(true);
    const agents = plan?.agents || ['support'];
    const website = plan?.website !== false;
    const stages = [
      ...(website ? ['Designing your website…', 'Sourcing imagery…', 'Writing copy…'] : []),
      'Creating your AI agents…', 'Wiring everything together…',
    ];
    let i = 0;
    setStage(stages[0]);
    const timer = setInterval(() => { i = (i + 1) % stages.length; setStage(stages[i]); }, 2200);

    try {
      const res = await api.generate({
        business_context: summary,
        business_name: businessName || 'My Business',
        agents,
        build_website: website,
        scrape_ref: scrapeRef || null,
      });
      clearInterval(timer);
      setBuilding(false);
      setMessages((m) => [...m, {
        role: 'assistant',
        content: `Your workspace is ready — ${website ? 'a four-page website and ' : ''}${agents.length} AI agent${agents.length > 1 ? 's' : ''}. Opening it now.`,
      }]);
      setTimeout(() => router.push(`/dashboard/workspace/${res.workspace_id}`), 1200);
    } catch (e) {
      clearInterval(timer);
      setBuilding(false);
      setMessages((m) => [...m, { role: 'assistant', content: `The build did not finish: ${e.message}` }]);
    }
  };

  return (
    <div className={styles.chatWrap}>
      <div className={styles.chatHeader}>
        <div>
          <h1>New build</h1>
          <span className={`${styles.online} ${online === false ? styles.onlineDown : ''}`}>
            <span className={`${styles.statusDot} ${online === false ? styles.statusDotDown : ''}`} aria-hidden="true" />
            {online === null ? 'Checking backend…' : online ? 'Backend online' : 'Backend unreachable'}
          </span>
        </div>
      </div>

      <div className={styles.messages}>
        <AnimatePresence initial={false}>
          {messages.map((m, i) => (
            <motion.div key={i} className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.ai}`}
              initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
              {m.role !== 'user' && <div className={styles.aiAvatar}><LogoMark size={18} /></div>}
              <div className={styles.bubble}>{m.content}</div>
            </motion.div>
          ))}
        </AnimatePresence>

        {busy && (
          <div className={`${styles.msg} ${styles.ai}`}>
            <div className={styles.aiAvatar}><LogoMark size={18} /></div>
            <div className={styles.bubble}><span className={styles.typing}><i /><i /><i /></span></div>
          </div>
        )}

        {building && (
          <motion.div className={styles.buildCard} initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}>
            <div className={styles.buildSpinner}><span className="spinner" /></div>
            <div>
              <div className={styles.buildTitle}>Building your workspace</div>
              <div className={styles.buildStage}>{stage}</div>
            </div>
          </motion.div>
        )}
        <div ref={endRef} />
      </div>

      {messages.length <= 1 && !busy && !building && (
        <div className={styles.suggestions}>
          {SUGGESTIONS.map((s) => (
            <button key={s} className={styles.chip} onClick={() => send(s)}>{s}</button>
          ))}
        </div>
      )}

      <form className={styles.inputBar} onSubmit={(e) => { e.preventDefault(); send(); }}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
          placeholder="Describe your business or paste a URL…"
          rows={1}
          disabled={building}
        />
        <button className="btn btn-primary" disabled={busy || building || !input.trim()} type="submit" aria-label="Send">
          {busy || building ? <span className="spinner" /> : <Icon name="arrowUp" size={18} />}
        </button>
      </form>
    </div>
  );
}
