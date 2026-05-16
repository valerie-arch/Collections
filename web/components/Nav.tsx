"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  AlertTriangle,
  FileText,
  LineChart,
  Wallet,
  Calculator,
  ClipboardList,
} from "lucide-react";
import clsx from "clsx";

const items = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/portfolio", label: "Portfolio trends", icon: LineChart },
  { href: "/activities", label: "Activities", icon: ClipboardList },
  { href: "/suspense", label: "Suspense", icon: Wallet },
  { href: "/exceptions", label: "Exceptions", icon: AlertTriangle },
  { href: "/quickbooks", label: "QuickBooks", icon: Calculator },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <aside className="w-64 shrink-0 bg-nav-600 flex flex-col text-white">
      <div className="px-5 py-5 flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-nav-700 flex items-center justify-center shrink-0 ring-1 ring-white/5">
          <Image
            src="/wahu-logo-dark.svg"
            alt="Wahu"
            width={28}
            height={28}
            priority
          />
        </div>
        <div>
          <div className="font-display text-lg tracking-tightest text-white leading-none">
            Wahu OS
          </div>
          <div className="text-[10px] uppercase tracking-wider text-white/40 mt-1">
            Collections
          </div>
        </div>
      </div>

      <div className="h-px bg-white/5 mx-3" />

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {items.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "group relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium",
                "transition-[background-color,color,box-shadow] duration-150 ease-spring",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400/60",
                active
                  ? "bg-nav-700 text-white ring-1 ring-accent-400/50"
                  : "text-white/60 hover:text-white hover:bg-white/5",
              )}
            >
              <Icon
                className={clsx(
                  "w-4 h-4 shrink-0",
                  active ? "text-accent-400" : "text-white/50 group-hover:text-white/80",
                )}
              />
              <span className="truncate">{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="px-5 py-3 border-t border-white/5 text-[10px] uppercase tracking-wider text-white/30 font-medium">
        Sprint 0 · v0.1.0
      </div>
    </aside>
  );
}
