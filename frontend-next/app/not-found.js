import Link from 'next/link';
import styles from './not-found.module.css';

export const metadata = {
  title: 'Page not found — Forge',
};

export default function NotFound() {
  return (
    <main className={styles.wrap}>
      <div className="morph-field" aria-hidden="true">
        <div className="morph-blob" />
        <div className="morph-blob" />
        <div className="morph-blob" />
      </div>

      <div className={`glass ${styles.card}`}>
        <span className={styles.code}>404</span>
        <h1 className={styles.title}>That page does not exist</h1>
        <p className={styles.body}>
          The link may be out of date, or the workspace it pointed to was renamed.
        </p>
        <div className={styles.actions}>
          <Link href="/" className="btn btn-primary">
            Back to home
          </Link>
          <Link href="/dashboard" className="btn btn-ghost">
            Go to dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
