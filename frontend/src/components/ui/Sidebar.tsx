/**
 * Sidebar — main navigation sidebar.
 */
"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";

const navLinks = [
  { href: "/", label: "Dashboard", icon: "◈" },
  { href: "/orders", label: "Orders", icon: "⟐" },
  { href: "/portfolio", label: "Portfolio", icon: "◎" },
  { href: "/strategies", label: "Strategies", icon: "⬡" },
  { href: "/mock", label: "Mock Testing", icon: "⏣" },
  { href: "/providers", label: "Providers", icon: "⊞" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

export function Sidebar() {
  const pathname = usePathname();

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

      <nav className="flex-1 p-4 space-y-1" role="navigation" aria-label="Main">
        {navLinks.map((link) => {
          const isActive =
            link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150",
                isActive
                  ? "text-white bg-white/10"
                  : "text-[var(--muted)] hover:text-white hover:bg-white/5",
              )}
              aria-current={isActive ? "page" : undefined}
            >
              <span className="text-base opacity-60">{link.icon}</span>
              {link.label}
            </Link>
          );
        })}
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
