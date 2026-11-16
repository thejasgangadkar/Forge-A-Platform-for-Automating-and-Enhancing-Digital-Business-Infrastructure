'use client';

import styles from './AgentGallery.module.css';

/**
 * AgentGallery — the agent templates a business can add.
 *
 * Every `type` here must exist in the backend's AGENT_TYPES, otherwise the
 * request silently degrades to a generic custom agent.
 *
 * Props:
 *   onSelect(agentType) — called when a card is chosen
 *   disabled            — disables all cards (e.g. while generating)
 */
const AGENT_TEMPLATES = [
  {
    type: 'receptionist',
    name: 'Receptionist',
    description: 'Greets visitors, answers general questions, and points them to the right place.',
    accent: 'blue',
    icon: ReceptionIcon,
  },
  {
    type: 'slot_booker',
    name: 'Slot Booker',
    description: 'Offers available time slots and reserves the one the visitor picks.',
    accent: 'green',
    icon: CalendarIcon,
  },
  {
    type: 'appointment_booker',
    name: 'Appointment Booker',
    description: 'Confirms the service, date and time, takes contact details, and books it.',
    accent: 'teal',
    icon: ClockIcon,
  },
  {
    type: 'support',
    name: 'Customer Support',
    description: 'Resolves problems and answers questions from your business knowledge.',
    accent: 'purple',
    icon: SupportIcon,
  },
  {
    type: 'lead_capture',
    name: 'Lead Capture',
    description: 'Engages visitors, works out what they need, and collects their contact details.',
    accent: 'orange',
    icon: LeadIcon,
  },
  {
    type: 'faq',
    name: 'FAQ Bot',
    description: 'Answers the questions people ask most about your services, hours and policies.',
    accent: 'pink',
    icon: FaqIcon,
  },
  {
    type: 'custom',
    name: 'Custom Agent',
    description: 'Describe any role in chat and it will be built to match.',
    accent: 'slate',
    icon: SparkIcon,
  },
];

export default function AgentGallery({ onSelect, disabled = false }) {
  return (
    <div className={styles.wrap}>
      <div className={styles.head}>
        <h3>Add an AI agent</h3>
        <p>Pick a role and it will be built from your business details.</p>
      </div>
      <div className={styles.grid}>
        {AGENT_TEMPLATES.map((agent) => {
          const Glyph = agent.icon;
          return (
            <button
              key={agent.type}
              type="button"
              onClick={() => !disabled && onSelect(agent.type)}
              disabled={disabled}
              className={`${styles.card} ${styles[agent.accent]}`}
              aria-label={`Create a ${agent.name} agent`}
            >
              <span className={styles.icon}><Glyph /></span>
              <span className={styles.name}>{agent.name}</span>
              <span className={styles.desc}>{agent.description}</span>
              <span className={styles.cue} aria-hidden="true">Create →</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── icons (inline SVG, no icon dependency) ── */
const svg = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };

function ReceptionIcon() {
  return <svg {...svg}><path d="M4 20v-1a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v1" /><circle cx="12" cy="7" r="4" /></svg>;
}
function CalendarIcon() {
  return <svg {...svg}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M8 3v4M16 3v4M3 11h18" /></svg>;
}
function ClockIcon() {
  return <svg {...svg}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>;
}
function SupportIcon() {
  return <svg {...svg}><path d="M18 8a6 6 0 0 0-12 0v5a3 3 0 0 0 3 3h1" /><path d="M3 13v-2a2 2 0 0 1 2-2h1v6H5a2 2 0 0 1-2-2zM21 13v-2a2 2 0 0 0-2-2h-1v6h1a2 2 0 0 0 2-2z" /></svg>;
}
function LeadIcon() {
  return <svg {...svg}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M19 8v6M22 11h-6" /></svg>;
}
function FaqIcon() {
  return <svg {...svg}><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.7" /><path d="M12 17h.01" /></svg>;
}
function SparkIcon() {
  return <svg {...svg}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8" /></svg>;
}
