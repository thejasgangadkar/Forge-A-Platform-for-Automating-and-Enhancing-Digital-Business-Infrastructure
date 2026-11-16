'use client';
import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { supabase } from '@/lib/supabase';
import { useAuth } from '@/lib/store';
import Logo from '@/components/Logo';
import styles from './login.module.css';

const GOOGLE_ENABLED = process.env.NEXT_PUBLIC_GOOGLE_AUTH === 'true';

function LoginInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { user } = useAuth();
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { setMode(params.get('mode') === 'signup' ? 'signup' : 'login'); }, [params]);
  useEffect(() => { if (user) router.push('/dashboard'); }, [user, router]);

  const submit = async (e) => {
    e.preventDefault();
    setErr(''); setBusy(true);
    try {
      if (mode === 'signup') {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      }
      router.push('/dashboard');
    } catch (e2) {
      setErr(e2.message || 'Something went wrong.');
    } finally { setBusy(false); }
  };

  const google = async () => {
    setErr('');
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}/dashboard` },
    });
    if (error) setErr(error.message);
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.glowBg} />
      <Link href="/" className={styles.back}>← Back</Link>
      <motion.div className={`${styles.card} glass`}
        initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
        <div className={styles.brand}><Logo size={24} /></div>
        <h1>{mode === 'signup' ? 'Create your account' : 'Welcome back'}</h1>
        <p className={styles.sub}>
          {mode === 'signup'
            ? 'Create an account to build a website and the agents for your business.'
            : 'Log in to your workspaces.'}
        </p>

        {GOOGLE_ENABLED && (
          <>
            <button className={styles.google} onClick={google} type="button">
              <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 4.1 29.6 2 24 2 11.8 2 2 11.8 2 24s9.8 22 22 22 22-9.8 22-22c0-1.3-.1-2.3-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 19 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 4.1 29.6 2 24 2 16.3 2 9.7 6.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 46c5.5 0 10.4-2.1 14.1-5.5l-6.5-5.5c-2 1.5-4.7 2.5-7.6 2.5-5.2 0-9.6-3.3-11.2-8l-6.5 5C9.6 41.6 16.2 46 24 46z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4.1 5.5l6.5 5.5C39.9 36.5 46 31 46 24c0-1.3-.1-2.3-.4-3.5z"/></svg>
              Continue with Google
            </button>
            <div className={styles.divider}><span>or</span></div>
          </>
        )}

        <form onSubmit={submit} className={styles.form}>
          <label>Email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@business.com" />
          </label>
          <label>Password
            <input type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
          </label>
          {err && <div className={styles.err}>{err}</div>}
          <button className={`btn btn-primary ${styles.submit}`} disabled={busy} type="submit">
            {busy ? <span className="spinner" /> : mode === 'signup' ? 'Create account' : 'Log in'}
          </button>
        </form>

        <div className={styles.switch}>
          {mode === 'signup' ? (
            <>Already have an account? <button onClick={() => setMode('login')}>Log in</button></>
          ) : (
            <>New to Forge? <button onClick={() => setMode('signup')}>Create one</button></>
          )}
        </div>
      </motion.div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className={styles.wrap}><span className="spinner" /></div>}>
      <LoginInner />
    </Suspense>
  );
}
