"use client";

import { signOut, useSession } from "next-auth/react";
import { LogOut, User } from "lucide-react";

function initialsOf(name?: string | null, email?: string | null) {
  const src = (name ?? email ?? "").trim();
  if (!src) return "?";
  const parts = src.split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function TopBar() {
  const { data: session } = useSession();
  const user = session?.user;

  if (!user) return null;

  return (
    <header className="sticky top-0 z-30 bg-canvas-raised/95 backdrop-blur border-b border-canvas-line">
      <div className="flex items-center justify-end px-8 py-3 gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-accent-100 text-accent-700 flex items-center justify-center font-semibold text-xs ring-1 ring-accent-400/40">
            {user.image ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={user.image}
                alt=""
                className="w-9 h-9 rounded-full object-cover"
              />
            ) : (
              initialsOf(user.name, user.email)
            )}
          </div>
          <div className="text-right">
            <div className="text-sm font-semibold text-ink leading-none">
              {user.name ?? "Wahu user"}
            </div>
            <div className="text-[11px] text-ink-fade font-mono mt-1">
              {user.email}
            </div>
          </div>
        </div>

        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="inline-flex items-center gap-2 rounded-lg border border-canvas-line bg-canvas-raised px-3.5 py-2 text-sm font-medium text-ink hover:border-ink-fade hover:bg-canvas-sunken transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
        >
          <LogOut className="w-3.5 h-3.5" />
          Sign Out
        </button>
      </div>
    </header>
  );
}
