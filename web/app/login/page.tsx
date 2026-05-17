"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { WahuLogo } from "@/components/WahuLogo";

function LoginInner() {
  const search = useSearchParams();
  const rawError = search.get("error");
  const callbackUrl = search.get("callbackUrl") ?? "/";

  const errorMessage =
    rawError === "Domain"
      ? "Only @wahu.me Google accounts can sign in."
      : rawError === "AccessDenied"
        ? "Access denied. Make sure you're signing in with your Wahu account."
        : rawError
          ? "Sign-in failed. Try again."
          : null;

  return (
    <div className="relative min-h-screen overflow-hidden bg-nav-600 flex items-center justify-center px-6">
      {/* Layered glow backdrop */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-90"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 0%, rgba(154,255,193,0.10) 0%, rgba(22,34,45,0) 60%), radial-gradient(80% 60% at 50% 100%, rgba(95,232,155,0.06) 0%, rgba(22,34,45,0) 70%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.04] mix-blend-overlay"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)' opacity='0.6'/></svg>\")",
        }}
      />

      <div className="relative w-full max-w-md">
        {/* Brand mark */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center mb-5">
            <WahuLogo size={72} />
          </div>
          <h1 className="text-4xl font-display tracking-tightest text-white">
            Welcome to Wahu
          </h1>
          <p className="text-sm text-white/50 mt-2">
            Sign in to access Collections
          </p>
        </div>

        {/* Sign-in card */}
        <div
          className="relative rounded-2xl bg-nav-700/80 backdrop-blur border border-white/5 px-8 py-8 shadow-floating"
          style={{ boxShadow: "0 0 0 1px rgba(154,255,193,0.08), 0 30px 60px -30px rgba(154,255,193,0.18)" }}
        >
          <div className="text-center mb-6">
            <h2 className="text-2xl font-display tracking-tightest text-white">
              Sign In
            </h2>
            <p className="text-xs text-white/40 mt-1.5">
              Only{" "}
              <span className="font-mono text-accent-400">@wahu.me</span>{" "}
              Google accounts
            </p>
          </div>

          {errorMessage && (
            <div className="mb-4 rounded-lg border border-clay-400/30 bg-clay-500/10 px-3 py-2.5 text-xs text-clay-400">
              {errorMessage}
            </div>
          )}

          <button
            onClick={() => signIn("google", { callbackUrl })}
            className="group w-full inline-flex items-center justify-center gap-3 rounded-lg bg-nav-500 border border-white/10 px-4 py-3 text-sm font-medium text-white hover:bg-nav-400 hover:border-accent-400/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-400/60 transition-[background-color,border-color,transform] duration-150 ease-spring active:scale-[0.99]"
          >
            <GoogleIcon />
            Sign in with Google
          </button>

          <div className="mt-6 text-[11px] text-white/35 text-center leading-relaxed">
            You'll be redirected to Google. After signing in with your wahu.me
            account you'll come back here.
          </div>
        </div>

        <div className="text-center mt-8 text-[11px] text-white/30 font-mono">
          Wahu Mobility · Collections Platform
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1A6.6 6.6 0 0 1 5.48 12c0-.73.13-1.44.36-2.1V7.07H2.18A11 11 0 0 0 1 12c0 1.78.43 3.47 1.18 4.93l3.66-2.83z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.83C6.71 7.31 9.14 5.38 12 5.38z"
      />
    </svg>
  );
}
