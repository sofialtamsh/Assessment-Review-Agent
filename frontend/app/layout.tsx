import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import AuthGate from "@/components/AuthGate";

export const metadata: Metadata = {
  title: "Assessment Review",
  description: "Multi-agent assessment question review pipeline",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen">
          <header className="border-b border-black/[0.06] bg-white/70 backdrop-blur sticky top-0 z-20">
            <div className="mx-auto max-w-6xl px-6 py-3.5 flex items-center justify-between">
              <Link href="/" className="flex items-center gap-2.5">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent-600 text-white text-sm font-bold">
                  AR
                </span>
                <span className="font-semibold tracking-tight">Assessment Review</span>
              </Link>
              <nav className="text-sm text-black/50">
                <span className="hidden sm:inline">NxtWave · DS &amp; ML</span>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-6 py-8">
            <AuthGate>{children}</AuthGate>
          </main>
        </div>
      </body>
    </html>
  );
}
