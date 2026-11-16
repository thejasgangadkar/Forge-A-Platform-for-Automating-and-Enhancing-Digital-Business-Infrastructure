'use client';
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { api } from '@/lib/api';
import Icon from '@/components/Icon';
import { LogoMark } from '@/components/Logo';
import VoiceChat from '@/components/VoiceChat';
import AgentGallery from '@/components/AgentGallery';
import LanguagePicker, { useLanguages } from '@/components/LanguagePicker';
import styles from './workspace.module.css';

export default function WorkspacePage() {
  const { id } = useParams();
  const [ws, setWs] = useState(null);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [canvas, setCanvas] = useState('site');     // site | agent | share
  const [refreshKey, setRefreshKey] = useState(0);

  const assetDir = ws?.business_profile?.asset_dir || id;
  const hasWebsite = (ws?.assets || []).some((a) => a.type === 'website');

  const load = useCallback(async () => {
    try {
      const [w, ag] = await Promise.all([api.getWorkspace(id), api.getAgents(id)]);
      setWs(w); setAgents(ag || []);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Pick a sensible default canvas based on what exists.
  useEffect(() => {
    if (!ws) return;
    if (hasWebsite) setCanvas('site');
    else if (agents.length) setCanvas('agent');
    else setCanvas('share');
  }, [ws, hasWebsite, agents.length]);

  const onChanged = () => { setRefreshKey((k) => k + 1); load(); };

  if (loading) return <div className={styles.center}><span className="spinner" /></div>;
  if (err) return <div className={styles.center}><p>{err}</p></div>;

  return (
    <div className={styles.split}>
      <AssistantPanel id={id} ws={ws} onChanged={onChanged} setCanvas={setCanvas} />
      <section className={styles.canvas}>
        <div className={styles.canvasTabs}>
          <button className={canvas === 'site' ? styles.cActive : ''} onClick={() => setCanvas('site')} disabled={!hasWebsite}>
            <Icon name="globe" size={15} /> Website
          </button>
          <button className={canvas === 'agent' ? styles.cActive : ''} onClick={() => setCanvas('agent')} disabled={!agents.length}>
            <Icon name="bot" size={15} /> Agents
          </button>
          <button className={canvas === 'share' ? styles.cActive : ''} onClick={() => setCanvas('share')}>
            <Icon name="external" size={15} /> Share
          </button>
          <button className={canvas === 'analytics' ? styles.cActive : ''} onClick={() => setCanvas('analytics')}>
            <Icon name="chart" size={15} /> Analytics
          </button>
        </div>
        <div className={styles.canvasBody}>
          {canvas === 'site' && (hasWebsite
            ? <SitePreview id={id} assetDir={assetDir} refreshKey={refreshKey} />
            : <Empty icon="globe" text="No website yet. Ask the assistant to build one." />)}
          {canvas === 'agent' && (agents.length
            ? <AgentsPanel id={id} agents={agents} />
            : <AgentGallery onSelect={async (type) => {
                try { await api.assist(id, `Add a ${type.replace('_', ' ')} agent`); onChanged(); }
                catch (e) { setErr(e.message); }
              }} disabled={false} />)}
          {canvas === 'share' && <SharePanel id={id} hasWebsite={hasWebsite} hasAgent={agents.length > 0} assetDir={assetDir} />}
          {canvas === 'analytics' && <AnalyticsPanel id={id} />}
        </div>
      </section>
    </div>
  );
}

/* ---------- Assistant (one chat that does everything) ---------- */
function AssistantPanel({ id, ws, onChanged, setCanvas }) {
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [speak, setSpeak] = useState('');
  const endRef = useRef(null);
  const { languages, code, setCode, locale } = useLanguages();

  // The workspace remembers the language it was last built in, so reopening it
  // does not silently revert to whatever this browser last used.
  const savedLang = ws?.business_profile?.language;
  useEffect(() => {
    if (savedLang && savedLang !== code) setCode(savedLang);
    // Intentionally keyed only on the saved value: including `code` would fight
    // the user every time they changed the picker.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedLang]);

  useEffect(() => {
    setMsgs([{ role: 'assistant', content:
      `This is your workspace for ${ws?.business_name || 'your business'}. Ask me to add a website, create an AI agent (receptionist, booking, support), or change anything — just tell me in plain words. You can type or speak in your own language.` }]);
  }, [ws?.business_name]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [msgs, busy]);

  const suggestions = [
    'Add a customer support agent',
    'Build a website for this business',
    'Add an appointment booking agent',
    'Make the website hero section darker',
  ];

  // `spoken` distinguishes a voice turn from a typed one: replies are read back
  // only when the user actually spoke, so typing never triggers unexpected audio.
  const send = async (text, spoken = false) => {
    const c = (text ?? input).trim(); if (!c || busy) return;
    setMsgs((m) => [...m, { role: 'user', content: c }]); setInput(''); setBusy(true);
    try {
      const r = await api.assist(id, c, code);
      setMsgs((m) => [...m, { role: 'assistant', content: r.reply }]);
      if (spoken && r.reply) setSpeak(r.reply);
      // The backend may detect a different language than the picker showed (the
      // user typed Hindi in Latin letters while it said English). Follow that,
      // so the next voice turn listens in the right language.
      if (r.language && r.language !== code) setCode(r.language);
      if (r.changed) {
        onChanged();
        if (r.action === 'add_website' || r.action === 'edit_website') setCanvas('site');
        if (r.action === 'add_agent' || r.action === 'edit_agent') setCanvas('agent');
      }
    } catch (e) {
      setMsgs((m) => [...m, { role: 'assistant', content: `That request failed: ${e.message}` }]);
    } finally { setBusy(false); }
  };

  return (
    <aside className={styles.assistant}>
      <div className={styles.aHead}>
        <div className={styles.aTitle}><LogoMark size={18} /> Workspace Assistant</div>
        <span className={styles.aSub}>{ws?.business_name}</span>
        <div className={styles.aLang}>
          <LanguagePicker
            languages={languages}
            code={code}
            onChange={setCode}
            disabled={busy}
            compact
            label="Language for chat, voice and generated pages"
          />
        </div>
      </div>
      <div className={styles.aMsgs}>
        <AnimatePresence initial={false}>
          {msgs.map((m, i) => (
            <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              className={`${styles.aMsg} ${m.role === 'user' ? styles.aU : styles.aA}`}>
              {m.content}
            </motion.div>
          ))}
        </AnimatePresence>
        {busy && <div className={`${styles.aMsg} ${styles.aA}`}><span className={styles.dots}><i /><i /><i /></span></div>}
        <div ref={endRef} />
      </div>
      {msgs.length <= 1 && !busy && (
        <div className={styles.aChips}>
          {suggestions.map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}
        </div>
      )}
      <form className={styles.aInput} onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Tell me what to build or change…" disabled={busy} />
        {/* Speaking a prompt is the point of this control: the transcript is
            sent immediately so a build can be started entirely by voice. */}
        <VoiceChat
          onTranscript={(text) => { setInput(text); send(text, true); }}
          speakText={speak}
          autoSpeak
          disabled={busy}
          locale={locale}
        />
        <button className="btn btn-primary" disabled={busy || !input.trim()} aria-label="Send"><Icon name="arrowUp" size={17} /></button>
      </form>
    </aside>
  );
}

/* ---------- Canvas panels ---------- */
function SitePreview({ id, assetDir, refreshKey }) {
  const [view, setView] = useState('desktop');
  const src = `${api.siteUrl(assetDir)}?v=${refreshKey}`;
  return (
    <div className={styles.siteWrap}>
      <div className={styles.siteBar}>
        <div className={styles.viewToggle}>
          <button className={view === 'desktop' ? styles.vActive : ''} onClick={() => setView('desktop')}><Icon name="desktop" size={15} /></button>
          <button className={view === 'mobile' ? styles.vActive : ''} onClick={() => setView('mobile')}><Icon name="mobile" size={15} /></button>
        </div>
        <div className={styles.siteActions}>
          <a href={api.siteUrl(assetDir)} target="_blank" rel="noreferrer" className="btn btn-ghost"><Icon name="external" size={14} /> Open</a>
          <a href={api.downloadUrl(id, 'website')} className="btn btn-ghost"><Icon name="download" size={14} /> Download</a>
        </div>
      </div>
      <div className={styles.frameHolder}>
        <iframe key={refreshKey} className={view === 'mobile' ? styles.mobileFrame : styles.desktopFrame} src={src} title="preview" />
      </div>
    </div>
  );
}

function AgentsPanel({ id, agents }) {
  const [active, setActive] = useState(agents[0]);
  useEffect(() => { setActive(agents[0]); }, [agents]);
  return (
    <div className={styles.agentsWrap}>
      <div className={styles.agentList}>
        {agents.map((a) => (
          <button key={a.id} className={`${styles.agentCard} ${active?.id === a.id ? styles.agentActive : ''}`} onClick={() => setActive(a)}>
            <div className={styles.agentName}>{a.name}</div>
            <div className={styles.agentType}>{(a.type || '').replace('_', ' ')}</div>
          </button>
        ))}
      </div>
      {active && <Sandbox id={id} agent={active} />}
    </div>
  );
}

function Sandbox({ id, agent }) {
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  // Text handed to the voice component to read aloud. Only set for replies that
  // arrive while voice mode is on, so enabling it never replays the backlog.
  const [speak, setSpeak] = useState('');
  const [voiceOn, setVoiceOn] = useState(false);
  const endRef = useRef(null);
  const { languages, code, setCode, locale } = useLanguages();

  // Default the sandbox to the language the agent was generated for, so testing
  // reflects what a real customer of that business would experience.
  useEffect(() => {
    if (agent?.language && agent.language !== code) setCode(agent.language);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent?.language]);

  useEffect(() => {
    setMsgs([{ role: 'assistant', content: agent.greeting || `Hello — what would you like to know about ${agent.name}?` }]);
    setSpeak('');
  }, [agent.id, agent.greeting]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [msgs, busy]);

  const send = async (text) => {
    const c = (text ?? input).trim(); if (!c || busy) return;
    const hist = msgs.map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: 'user', content: c }]); setInput(''); setBusy(true);
    try {
      const r = await api.agentChat(id, c, hist, agent.id, locale);
      setMsgs((m) => [...m, { role: 'assistant', content: r.reply }]);
      if (voiceOn) setSpeak(r.reply);
    } catch (e) {
      setMsgs((m) => [...m, { role: 'assistant', content: `That request failed: ${e.message}` }]);
    } finally { setBusy(false); }
  };

  return (
    <div className={styles.sandbox}>
      <div className={styles.sandboxHead}>
        <span>Test {agent.name} live</span>
        <div className={styles.sandboxTools}>
          {/* Testing in another language matters: a customer may not speak the
              language the business configured. */}
          <LanguagePicker
            languages={languages} code={code} onChange={setCode}
            disabled={busy} compact label="Language to test the agent in"
          />
          <label className={styles.voiceToggle}>
            <input type="checkbox" checked={voiceOn}
              onChange={(e) => { setVoiceOn(e.target.checked); if (!e.target.checked) setSpeak(''); }} />
            Speak replies
          </label>
        </div>
      </div>
      <div className={styles.sandboxMsgs}>
        {msgs.map((m, i) => <div key={i} className={`${styles.sMsg} ${m.role === 'user' ? styles.sUser : styles.sAgent}`}>{m.content}</div>)}
        {busy && <div className={`${styles.sMsg} ${styles.sAgent}`}><span className={styles.dots}><i /><i /><i /></span></div>}
        <div ref={endRef} />
      </div>
      <form className={styles.sandboxInput} onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask the agent…" />
        {/* Speaking a transcript straight away keeps a voice conversation hands-free. */}
        <VoiceChat
          onTranscript={(text) => { setInput(text); send(text); }}
          speakText={speak}
          autoSpeak={voiceOn}
          disabled={busy}
          locale={locale}
        />
        <button className="btn btn-primary" disabled={busy} aria-label="Send"><Icon name="arrowUp" size={16} /></button>
      </form>
    </div>
  );
}

function SharePanel({ id, hasWebsite, hasAgent, assetDir }) {
  const [embed, setEmbed] = useState(null);
  const [copied, setCopied] = useState('');
  useEffect(() => { api.getEmbed(id).then(setEmbed).catch(() => {}); }, [id]);
  const copy = (text, which) => { navigator.clipboard.writeText(text); setCopied(which); setTimeout(() => setCopied(''), 1600); };

  return (
    <div className={styles.share}>
      {hasAgent && (
        <div className={styles.shareCard}>
          <div className={styles.shareHl}><Icon name="chat" size={18} /></div>
          <h3>Share your AI assistant</h3>
          <p>Send this link to customers. It opens a ready-to-use chat page — no install, no login.</p>
          {embed ? (
            <div className={styles.linkRow}>
              <a href={embed.share_link} target="_blank" rel="noreferrer" className={styles.linkText}>{embed.share_link}</a>
              <button className="btn btn-primary" onClick={() => copy(embed.share_link, 'link')}>{copied === 'link' ? 'Copied' : 'Copy link'}</button>
            </div>
          ) : <span className="spinner" />}
        </div>
      )}

      {hasWebsite && (
        <div className={styles.shareCard}>
          <div className={styles.shareHl}><Icon name="globe" size={18} /></div>
          <h3>Your website is live</h3>
          <p>Your generated site already has the assistant built in. Share it or download the code.</p>
          <div className={styles.linkRow}>
            <a href={api.siteUrl(assetDir)} target="_blank" rel="noreferrer" className={styles.linkText}>{api.siteUrl(assetDir)}</a>
            <a className="btn btn-ghost" href={api.downloadUrl(id, 'website')}><Icon name="download" size={14} /> Code</a>
          </div>
        </div>
      )}

      {hasAgent && embed && (
        <div className={styles.shareCard}>
          <div className={styles.shareHl}><Icon name="layers" size={18} /></div>
          <h3>Add it to an existing website</h3>
          <p>Already have a site? Paste this one line before <code>&lt;/body&gt;</code> — a chat bubble appears, no coding needed.</p>
          <pre className={styles.code}>{embed.snippet}</pre>
          <button className="btn btn-ghost" onClick={() => copy(embed.snippet, 'snip')}>{copied === 'snip' ? 'Copied' : 'Copy snippet'}</button>
        </div>
      )}

      {!hasWebsite && !hasAgent && <Empty icon="external" text="Build a website or agent first, then share it here." />}
    </div>
  );
}

function Empty({ icon, text }) {
  return (
    <div className={styles.empty}>
      <div className={styles.emptyIcon}><Icon name={icon} size={30} /></div>
      <p>{text}</p>
    </div>
  );
}


/* ---------- Analytics Panel ---------- */
function AnalyticsPanel({ id }) {
  const [data, setData] = useState(null);
  const [period, setPeriod] = useState('week');
  useEffect(() => {
    api.analytics(id, period).then(setData).catch(() => setData({ total_visits: 0, total_chats: 0, total_leads: 0 }));
  }, [id, period]);

  if (!data) return <div className={styles.center}><span className="spinner" /></div>;

  return (
    <div className={styles.analytics}>
      <div className={styles.periodBar} role="group" aria-label="Analytics period">
        {['day', 'week', 'month'].map((p) => (
          <button key={p} onClick={() => setPeriod(p)}
            className={`${styles.periodBtn} ${period === p ? styles.periodActive : ''}`}
            aria-pressed={period === p}>
            {p.charAt(0).toUpperCase() + p.slice(1)}
          </button>
        ))}
      </div>
      <div className={styles.statGrid}>
        <StatCard label="Site visits" value={data.total_visits} />
        <StatCard label="Agent chats" value={data.total_chats} />
        <StatCard label="Leads captured" value={data.total_leads} />
      </div>
    </div>
  );
}

function StatCard({ label, value }) {
  return (
    <div className={styles.statCard}>
      <div className={styles.statValue}>{value}</div>
      <div className={styles.statLabel}>{label}</div>
    </div>
  );
}
