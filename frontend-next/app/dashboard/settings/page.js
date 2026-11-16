'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/store';
import { api } from '@/lib/api';
import styles from './settings.module.css';

export default function Settings() {
  const { user, signOut } = useAuth();
  const router = useRouter();

  const [workspaces, setWorkspaces] = useState([]);
  const [health, setHealth] = useState(null);
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pendingId, setPendingId] = useState(null);   // awaiting confirmation
  const [deletingId, setDeletingId] = useState(null); // request in flight
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    // Platform info is informational, so a failure there must not hide the
    // workspace list, which is the part users act on.
    const [ws, h, ch] = await Promise.all([
      api.listWorkspaces().catch(() => []),
      api.health().catch(() => null),
      api.channels().catch(() => ({ channels: [] })),
    ]);
    setWorkspaces(Array.isArray(ws) ? ws : []);
    setHealth(h);
    setChannels(ch?.channels || []);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const remove = async (id, name) => {
    setDeletingId(id);
    setNotice(null);
    try {
      await api.deleteWorkspace(id);
      setWorkspaces((list) => list.filter((w) => w.id !== id));
      setNotice({ type: 'ok', text: `Deleted "${name}" and all of its assets.` });
      // The sidebar reads the workspace list, so refresh the route tree too.
      router.refresh();
    } catch (e) {
      setNotice({ type: 'error', text: `Could not delete "${name}": ${e.message}` });
    } finally {
      setDeletingId(null);
      setPendingId(null);
    }
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Settings</h1>
      <p className={styles.subtitle}>Your account, your workspaces, and what this build supports.</p>

      {/* ── account ── */}
      <section className={`${styles.card} glass`}>
        <h3>Account</h3>
        <p className={styles.hint}>Signed in with Supabase authentication.</p>
        <Row label="Email" value={user?.email || '—'} />
        <Row label="User ID" value={user?.id || '—'} />
        <div className={styles.accountActions}>
          <button className="btn btn-ghost" onClick={signOut}>Sign out</button>
        </div>
      </section>

      {/* ── workspaces ── */}
      <section className={`${styles.card} glass`}>
        <h3>Workspaces</h3>
        <p className={styles.hint}>
          Deleting a workspace permanently removes its website, agents, chat history and
          memory, and takes its shared link and embedded widget offline. This cannot be undone.
        </p>

        {loading && <div className={styles.empty}>Loading…</div>}
        {!loading && workspaces.length === 0 && (
          <div className={styles.empty}>No workspaces yet. Start one from “New Build”.</div>
        )}

        {workspaces.map((w) => {
          const name = w.business_name || w.name || 'Untitled';
          const isPending = pendingId === w.id;
          const isDeleting = deletingId === w.id;
          return (
            <div key={w.id} className={styles.wsRow}>
              <div className={styles.wsMeta}>
                <div className={styles.wsName}>{name}</div>
                <div className={styles.wsSub}>
                  {w.created_at ? new Date(w.created_at).toLocaleDateString() : ''}
                  {' · '}{w.id.slice(0, 8)}…
                </div>
              </div>

              {isPending ? (
                <div className={styles.confirm}>
                  <span className={styles.confirmText}>Delete permanently?</span>
                  <button className={styles.cancel} onClick={() => setPendingId(null)}
                    disabled={isDeleting}>Cancel</button>
                  <button className={styles.danger} onClick={() => remove(w.id, name)}
                    disabled={isDeleting}>
                    {isDeleting ? 'Deleting…' : 'Yes, delete'}
                  </button>
                </div>
              ) : (
                <button className={styles.danger} onClick={() => setPendingId(w.id)}
                  disabled={Boolean(deletingId)}>Delete</button>
              )}
            </div>
          );
        })}

        {notice && (
          <div className={notice.type === 'ok' ? styles.ok : styles.error}>{notice.text}</div>
        )}
      </section>

      {/* ── delivery channels ── */}
      <section className={`${styles.card} glass`}>
        <h3>Delivery channels</h3>
        <p className={styles.hint}>
          Where your agents can talk to customers. “Planned” channels are built into the
          architecture and need provider credentials to switch on.
        </p>
        {channels.length === 0 && <div className={styles.empty}>Unavailable.</div>}
        {channels.map((c) => (
          <div key={c.name} className={styles.row}>
            <span className={styles.rowLabel}>{c.label}</span>
            <StatusPill status={c.status} />
          </div>
        ))}
      </section>

      {/* ── platform ── */}
      <section className={`${styles.card} glass`}>
        <h3>Platform</h3>
        <p className={styles.hint}>
          Models are configured server-side and can be swapped without code changes.
        </p>
        <Row label="Backend" value={health ? `v${health.version}` : 'unreachable'} />
        <Row label="API endpoint" value={api.base} />
        <Row label="Agent types" value={
          health?.agent_types ? `${health.agent_types.length} available` : '—'} />
        <Row label="Active channels" value={
          health?.channels?.length ? health.channels.join(', ') : '—'} />
      </section>
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className={styles.row}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowValue}>{value}</span>
    </div>
  );
}

function StatusPill({ status }) {
  const cls = status === 'live' ? styles.live
    : status === 'planned' ? styles.planned : styles.needs;
  return (
    <span className={`${styles.pill} ${cls}`}>
      <span className={styles.dot} />{status}
    </span>
  );
}
