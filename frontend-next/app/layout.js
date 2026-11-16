import './globals.css';

export const metadata = {
  title: 'Forge — Build Your Business with AI',
  description:
    'Forge is an agentic AI platform that builds websites and AI agents for your business through chat. No code. No manual work.',
  icons: {
    icon: [{ url: '/forge-mark.svg', type: 'image/svg+xml' }],
    apple: [{ url: '/forge-mark.svg' }],
  },
};

// Keeps the mobile browser chrome and native controls (selects, scrollbars) on
// the same light palette as the app instead of the OS dark theme.
export const viewport = {
  themeColor: '#f6f4fb',
  colorScheme: 'light',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Quicksand:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
