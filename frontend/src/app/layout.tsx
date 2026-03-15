import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trade Platform – Dashboard",
  description: "Multi-provider automated trading platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen antialiased" style={{ fontFamily: "'Outfit', sans-serif" }}>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 overflow-auto">{children}</main>
        </div>
      </body>
    </html>
  );
}

function Sidebar() {
  const links = [
    { href: "/", label: "Dashboard", icon: "◈" },
    { href: "/market", label: "Market", icon: "◇" },
    { href: "/orders", label: "Orders", icon: "⟐" },
    { href: "/portfolio", label: "Portfolio", icon: "◎" },
    { href: "/strategies", label: "Strategies", icon: "⬡" },
    { href: "/backtest", label: "Backtest", icon: "⟳" },
    { href: "/mock", label: "Mock Testing", icon: "⏣" },
    { href: "/providers", label: "Providers", icon: "⊞" },
    { href: "/settings", label: "Settings", icon: "⚙" },
  ];

  return (
    <aside className="w-64 border-r border-[var(--card-border)] bg-[#080808] flex flex-col">
      <div className="p-6 border-b border-[var(--card-border)]">
        <h1
          className="text-xl font-bold tracking-tight"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          <span className="text-brand-400">◆</span> TradeOS
        </h1>
        <p className="text-xs text-[var(--muted)] mt-1">v0.1.0 · Multi-Provider</p>
      </div>

      <nav className="flex-1 p-4 space-y-1">
        {links.map((link) => (
          <a
            key={link.href}
            href={link.href}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-[var(--muted)]
              hover:text-white hover:bg-white/5 transition-all duration-150"
          >
            <span className="text-base opacity-60">{link.icon}</span>
            {link.label}
          </a>
        ))}
      </nav>

      <div className="p-4 border-t border-[var(--card-border)]">
        <div className="flex items-center gap-2 px-3 py-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs text-[var(--muted)]">System Online</span>
        </div>
      </div>
    </aside>
  );
}
