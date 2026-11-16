'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import styles from './support.module.css';

/* Answers describe the CURRENT interface. The earlier version referred to an
   "Edit by chat" tab that no longer exists — the workspace is now a single
   assistant conversation — so wrong instructions were worse than none. */
const SECTIONS = [
  {
    heading: 'Getting started',
    items: [
      {
        q: 'How do I build my first website?',
        a: 'Open “New Build” and describe your business in plain language — what you do, your services, your hours. Or paste the URL of a site you already have. Forge reads it, builds a four-page website plus the AI agents you asked for, and opens a workspace for you.',
      },
      {
        q: 'How long does a build take?',
        a: 'Around two minutes for a full four-page site with an agent. You will see progress messages while it works. You can leave the page — the workspace is saved either way.',
      },
      {
        q: 'What should I say to get the best result?',
        a: 'Be specific. Real service names, real opening hours, a phone number, and who your customers are. The more concrete detail you give, the more specific the copy on your site will be.',
      },
    ],
  },
  {
    heading: 'Editing and agents',
    items: [
      {
        q: 'How do I change something after it is built?',
        a: 'Just tell the assistant on the left of your workspace, in plain words — “make the hero darker”, “add a refund FAQ”, “change the phone number”. Changes to shared parts like the navigation or footer are applied across every page automatically.',
      },
      {
        q: 'What kinds of AI agent can I have?',
        a: 'Seven roles: receptionist, slot booker, appointment booker, customer support, lead capture, FAQ bot, and a fully custom agent you describe yourself. Ask the assistant for one, or pick a card from the Agents tab.',
      },
      {
        q: 'Can my agents actually do things, not just talk?',
        a: 'Yes. They can book appointments, capture a lead’s contact details, and escalate to a human. Those actions are recorded and show up in your Analytics tab.',
      },
      {
        q: 'Why does my agent say it does not know something?',
        a: 'Agents answer strictly from your business information and will not invent prices, hours or addresses. If it keeps saying it does not know, add that detail by telling the assistant, and the agent will pick it up.',
      },
      {
        q: 'Can customers talk to my agent by voice?',
        a: 'Yes. There is a microphone button in the agent sandbox, on your shared link, and in the embedded widget. It uses your browser’s built-in speech, so there is nothing to install and no extra cost.',
      },
    ],
  },
  {
    heading: 'Sharing and publishing',
    items: [
      {
        q: 'How do I put this in front of customers?',
        a: 'Open the Share tab. You get a link you can send to anyone — it opens a ready-to-use chat page with no login. Your generated website is also live there, with the assistant already built in.',
      },
      {
        q: 'I already have a website. Can I still use the agent?',
        a: 'Yes. The Share tab gives you a one-line snippet. Paste it before the closing </body> tag of your existing site and a chat bubble appears. No other changes needed.',
      },
      {
        q: 'Can I use my own domain name?',
        a: 'Not yet. Sites are currently published on a Forge address. Attaching your own domain is planned.',
      },
      {
        q: 'Can I download the code?',
        a: 'Yes. Use the Download button in the Website tab to get a zip of every page, plus the sitemap and robots.txt.',
      },
    ],
  },
  {
    heading: 'Troubleshooting',
    items: [
      {
        q: 'The preview is blank or the page will not load.',
        a: 'The backend may not be running. Check the status panel below — if it says unreachable, start the backend and reload.',
      },
      {
        q: 'A build failed or produced a plain-looking page.',
        a: 'Usually a temporary limit on the free AI tier. Wait a minute and ask the assistant to try again. Forge automatically switches to a backup provider when one is unavailable.',
      },
      {
        q: 'The agent said I am sending messages too quickly.',
        a: 'Shared links are rate limited to protect your usage allowance from abuse. Wait a moment and continue — normal conversation will not hit the limit.',
      },
      {
        q: 'I deleted a workspace by mistake.',
        a: 'Deletion is permanent and removes the site, agents, history and memory. There is no undo, which is why it asks for confirmation first.',
      },
    ],
  },
];

export default function Support() {
  const [status, setStatus] = useState('checking');
  const [info, setInfo] = useState(null);
  const [open, setOpen] = useState('0-0');

  useEffect(() => {
    api.health()
      .then((h) => { setInfo(h); setStatus('online'); })
      .catch(() => setStatus('offline'));
  }, []);

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Help &amp; Support</h1>
      <p className={styles.subtitle}>
        How Forge works, and what to do when something looks wrong.
      </p>

      {SECTIONS.map((section, si) => (
        <section key={section.heading} className={styles.section}>
          <h2 className={styles.heading}>{section.heading}</h2>
          <div className={styles.list}>
            {section.items.map((item, ii) => {
              const key = `${si}-${ii}`;
              const isOpen = open === key;
              return (
                <div key={key} className={`${styles.item} glass`}>
                  <button
                    className={styles.q}
                    onClick={() => setOpen(isOpen ? null : key)}
                    aria-expanded={isOpen}
                  >
                    <span>{item.q}</span>
                    <svg
                      className={`${styles.chev} ${isOpen ? styles.chevOpen : ''}`}
                      width="14" height="14" viewBox="0 0 24 24" fill="none"
                      stroke="currentColor" strokeWidth="2.2"
                      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
                    >
                      <path d="M6 9l6 6 6-6" />
                    </svg>
                  </button>
                  {isOpen && <p className={styles.a}>{item.a}</p>}
                </div>
              );
            })}
          </div>
        </section>
      ))}

      <section className={styles.section}>
        <h2 className={styles.heading}>System status</h2>
        <div className={`${styles.item} ${styles.statusCard} glass`}>
          <div className={styles.statusRow}>
            <span className={styles.statusLabel}>Backend</span>
            <span className={`${styles.pill} ${status === 'online' ? styles.up
              : status === 'offline' ? styles.down : styles.wait}`}>
              <span className={styles.dot} />
              {status === 'online' ? `online · v${info?.version || '?'}`
                : status === 'offline' ? 'unreachable' : 'checking…'}
            </span>
          </div>
          {status === 'offline' && (
            <p className={`${styles.a} ${styles.statusNote}`}>
              Forge cannot reach its backend at <code>{api.base}</code>. Start the
              backend, then reload this page.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
