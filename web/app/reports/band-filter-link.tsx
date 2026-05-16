"use client";

import { useRouter, useSearchParams } from "next/navigation";

export function BandFilterLink({
  band,
  children,
}: {
  band: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const search = useSearchParams();
  const active = (search.get("band") ?? "All") === band;

  const handleClick = () => {
    const params = new URLSearchParams(search.toString());
    if (active) {
      params.delete("band");
    } else {
      params.set("band", band);
    }
    router.replace(`?${params.toString()}#riders-table`, { scroll: true });
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`block w-full text-left rounded-md transition-colors px-2 -mx-2
                  ${active ? "bg-canvas-sunken ring-1 ring-accent-500/30" : "hover:bg-canvas-sunken/60"}`}
    >
      {children}
    </button>
  );
}
