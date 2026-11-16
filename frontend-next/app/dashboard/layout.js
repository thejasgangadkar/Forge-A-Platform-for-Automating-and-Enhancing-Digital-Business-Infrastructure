'use client';
import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@/lib/store';
import { api } from '@/lib/api';
import Icon from '@/components/Icon';
import Logo from '@/components/Logo';
import styles from './dashboard.module.css';

export default function DashboardLayout({ children }) {
  const { user, loading, signOut } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [workspaces, setWorkspaces] = useState([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.push('/login');
  }, [user, loading, router]);

  useEffect(() => {
    if (user) api.listWorkspaces().then(setWorkspaces).catch(() => {});
  }, [user, pathname]);

  if (loading || !user) {
    return <div className={styles.fullCenter}><span className="spinner" /></div>;
  }

  const nav = [
    { href: '/dashboard', label: 'New build', icon: 'spark', exact: true },
    { href: '/dashboard/support', label: 'Help & support', icon: 'chat' },
    { href: '/dashboard/settings', label: 'Settings', icon: 'settings' },
  ];

  return (
    <div className={styles.shell}>
      <button className={styles.menuBtn} onClick={() => setOpen(!open)} aria-label="Menu">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
      </button>
      <aside className={`${styles.sidebar} ${open ? styles.sidebarOpen : ''}`}>
        <Link href="/dashboard" className={styles.brand} onClick={() => setOpen(false)} aria-label="Forge dashboard">
          <Logo size={24} />
        </Link>

        <nav className={styles.navList}>
          {nav.map((n) => {
            const active = n.exact ? pathname === n.href : pathname.startsWith(n.href);
            return (
              <Link key={n.href} href={n.href} onClick={() => setOpen(false)}
                className={`${styles.navItem} ${active ? styles.navActive : ''}`}>
                <Icon name={n.icon} size={18} /> {n.label}
              </Link>
            );
          })}
        </nav>

        <div className={styles.wsSection}>
          <div className={styles.wsLabel}>Workspaces</div>
          <div className={styles.wsList}>
            {workspaces.length === 0 && <div className={styles.wsEmpty}>No workspaces yet</div>}
            {workspaces.map((w) => {
              const active = pathname === `/dashboard/workspace/${w.id}`;
              return (
                <Link key={w.id} href={`/dashboard/workspace/${w.id}`} onClick={() => setOpen(false)}
                  className={`${styles.wsItem} ${active ? styles.wsActive : ''}`}>
                  <span className={styles.wsDot} />
                  <span className={styles.wsName}>{w.business_name || w.name || 'Untitled'}</span>
                </Link>
              );
            })}
          </div>
        </div>

        <div className={styles.userBox}>
          <div className={styles.avatar}>{(user.email || '?')[0].toUpperCase()}</div>
          <div className={styles.userMeta}>
            <span className={styles.userEmail}>{user.email}</span>
            <button onClick={signOut} className={styles.signout}>Sign out</button>
          </div>
        </div>
      </aside>

      <main className={styles.content}>{children}</main>
      {open && <div className={styles.overlay} onClick={() => setOpen(false)} />}
    </div>
  );
}
