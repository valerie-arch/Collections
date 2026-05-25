"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * Global navigation feedback. Two signals fire whenever the user clicks
 * a Link or submits a navigating form:
 *   1. body.style.cursor = "progress" — the OS cursor turns into the
 *      platform's loading indicator while the server renders.
 *   2. A 2px accent-tinted top bar slides in across the viewport.
 *
 * We can't subscribe to Next.js App Router navigation events directly
 * (the framework doesn't expose them), so we listen for link clicks +
 * form submissions to start the indicator, and clear it as soon as the
 * URL settles via usePathname / useSearchParams.
 */
export function NavigationProgress() {
  const pathname = usePathname();
  const search = useSearchParams();
  const [active, setActive] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clear the indicator whenever the URL changes — that's our signal
  // the server-rendered page actually mounted.
  useEffect(() => {
    setActive(false);
    document.body.style.cursor = "";
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, [pathname, search]);

  // Detect navigation starts — intercept internal link clicks + form GETs.
  useEffect(() => {
    const start = () => {
      setActive(true);
      document.body.style.cursor = "progress";
      // Safety net: if a navigation hangs or is canceled, drop the
      // indicator after 10s so the page never sticks in 'progress'.
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        setActive(false);
        document.body.style.cursor = "";
      }, 10_000);
    };

    const onClick = (e: MouseEvent) => {
      // Only react to plain left clicks on real anchor elements.
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as HTMLElement)?.closest("a");
      if (!a) return;
      const href = a.getAttribute("href");
      if (!href || href.startsWith("#")) return;
      // Skip external links (different origin) and downloads.
      try {
        const url = new URL(href, window.location.href);
        if (url.origin !== window.location.origin) return;
      } catch {
        return;
      }
      if (a.getAttribute("target") === "_blank") return;
      if (a.hasAttribute("download")) return;
      // Same path AND same query → not really a nav, skip.
      const sameUrl =
        a.pathname === window.location.pathname
        && a.search === window.location.search;
      if (sameUrl) return;
      start();
    };

    const onSubmit = (e: SubmitEvent) => {
      const form = e.target as HTMLFormElement | null;
      if (!form) return;
      // Only GETs cause a same-page navigation we should indicate.
      const method = (form.getAttribute("method") || "get").toLowerCase();
      if (method !== "get") return;
      start();
    };

    document.addEventListener("click", onClick, true);
    document.addEventListener("submit", onSubmit, true);
    return () => {
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("submit", onSubmit, true);
      if (timer.current) clearTimeout(timer.current);
      document.body.style.cursor = "";
    };
  }, []);

  return (
    <div
      aria-hidden
      className={`fixed inset-x-0 top-0 z-[60] h-[2px] pointer-events-none transition-opacity duration-150 ${
        active ? "opacity-100" : "opacity-0"
      }`}
    >
      <div
        className={`h-full bg-accent-500 ${
          active ? "animate-[nav-progress_1.2s_ease-out_infinite]" : ""
        }`}
        style={{ transformOrigin: "left" }}
      />
      <style>{`
        @keyframes nav-progress {
          0%   { transform: scaleX(0);   opacity: 1; }
          60%  { transform: scaleX(0.7); opacity: 1; }
          100% { transform: scaleX(1);   opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}
