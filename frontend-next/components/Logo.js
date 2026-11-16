'use client';

import { useId } from 'react';
import styles from './Logo.module.css';

/* Forge brand mark.
   A squircle with an asymmetrical bottom-right corner (the liquid-morphism
   silhouette), a molten violet → pink gradient, a glass sheen across the
   top-left, and a white F. Geometry is plain SVG — no filters — so it stays
   crisp from 16px favicons up to the login card. */

export function LogoMark({ size = 28, className = '' }) {
  // Gradient ids must be unique per instance or multiple logos on one page
  // will all reference the first definition.
  const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
  const tile = `forgeTile${uid}`;
  const sheen = `forgeSheen${uid}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      className={className}
      // Decorative: the accessible name always comes from the wordmark or the
      // link's aria-label, so announcing "Forge" here would double it.
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={tile} x1="5" y1="2" x2="36" y2="38" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#7A63F2" />
          <stop offset="0.5" stopColor="#6B57E8" />
          <stop offset="1" stopColor="#FF6FB5" />
        </linearGradient>
        <linearGradient id={sheen} x1="7" y1="3" x2="25" y2="26" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.42" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>

      <path
        d="M13 2H27C33.6 2 38 6.4 38 13V23C38 31.3 31.3 38 23 38H13C6.4 38 2 33.6 2 27V13C2 6.4 6.4 2 13 2Z"
        fill={`url(#${tile})`}
      />
      <path
        d="M13 2H27C33.6 2 38 6.4 38 13V23C38 31.3 31.3 38 23 38H13C6.4 38 2 33.6 2 27V13C2 6.4 6.4 2 13 2Z"
        fill={`url(#${sheen})`}
      />
      <path
        d="M13 2H27C33.6 2 38 6.4 38 13V23C38 31.3 31.3 38 23 38H13C6.4 38 2 33.6 2 27V13C2 6.4 6.4 2 13 2Z"
        fill="none"
        stroke="#ffffff"
        strokeOpacity="0.38"
        strokeWidth="1"
      />

      {/* The F: stem plus two arms, all with rounded ends. */}
      <rect x="12" y="11" width="4.8" height="18.5" rx="2.4" fill="#ffffff" />
      <rect x="12" y="11" width="15.5" height="4.8" rx="2.4" fill="#ffffff" />
      <rect x="12" y="18.9" width="11" height="4.8" rx="2.4" fill="#ffffff" />
    </svg>
  );
}

export default function Logo({ size = 26, text = 'Forge', className = '' }) {
  return (
    <span className={`${styles.wrap} ${className}`}>
      <LogoMark size={size} />
      {text ? (
        <span className={styles.word} style={{ fontSize: Math.round(size * 0.72) }}>
          {text}
        </span>
      ) : null}
    </span>
  );
}
