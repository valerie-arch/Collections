"use client";

import { useState, useRef, useEffect } from "react";
import { Info } from "lucide-react";

/**
 * Small accessible tooltip. Shows on hover (desktop) and click (touch).
 * Renders a `?` icon by default; pass a custom child to override.
 */
export function Tooltip({
  content,
  children,
  side = "bottom",
  align = "start",
}: {
  content: React.ReactNode;
  children?: React.ReactNode;
  side?: "top" | "bottom";
  align?: "start" | "center" | "end";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const placement =
    side === "top"
      ? "bottom-full mb-2"
      : "top-full mt-2";
  const alignment =
    align === "end"
      ? "right-0"
      : align === "center"
      ? "left-1/2 -translate-x-1/2"
      : "left-0";

  return (
    <span
      ref={ref}
      className="relative inline-flex items-center"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          setOpen((v) => !v);
        }}
        aria-label="More info"
        className="inline-flex items-center text-ink-fade hover:text-accent-600
                   transition-colors focus-visible:outline-none focus-visible:ring-2
                   focus-visible:ring-accent-500 focus-visible:ring-offset-1
                   focus-visible:ring-offset-canvas rounded-full"
      >
        {children ?? <Info className="w-3 h-3" />}
      </button>
      {open && (
        <span
          role="tooltip"
          className={`absolute z-50 ${placement} ${alignment}
                      w-72 rounded-md bg-ink text-canvas-raised
                      px-3 py-2.5 text-xs leading-relaxed
                      shadow-floating pointer-events-none`}
        >
          {content}
        </span>
      )}
    </span>
  );
}
