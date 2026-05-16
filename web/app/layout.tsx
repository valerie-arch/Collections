import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/Nav";
import { TopBar } from "@/components/TopBar";
import { SessionProvider } from "@/components/SessionProvider";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";

export const metadata: Metadata = {
  title: "Wahu Collections Reconciliation",
  description: "Daily/weekly collections reconciliation across Wahu Fleet & TSA",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await getServerSession(authOptions);
  return (
    <html lang="en">
      <body>
        <SessionProvider>
          {session ? (
            <div className="flex min-h-screen bg-canvas">
              <Nav />
              <div className="flex-1 min-w-0 flex flex-col">
                <TopBar />
                <main className="flex-1 min-w-0">{children}</main>
              </div>
            </div>
          ) : (
            <>{children}</>
          )}
        </SessionProvider>
      </body>
    </html>
  );
}
