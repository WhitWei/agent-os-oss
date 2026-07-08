import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Link from "next/link";
import { Activity, ShieldAlert, GitMerge } from "lucide-react";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Agent OS Dashboard",
  description: "Governance and Monitoring Console",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${geistSans.variable} ${geistMono.variable} h-full antialiased bg-black text-white flex`}>
        <aside className="w-64 border-r border-zinc-800 p-6 flex flex-col gap-6 min-h-screen bg-zinc-950">
          <div className="font-bold text-xl mb-4 tracking-wider text-emerald-500">Agent OS</div>
          <nav className="flex flex-col gap-4">
            <Link href="/" className="flex items-center gap-3 text-zinc-400 hover:text-emerald-400 transition-colors">
              <Activity size={18} /> Overview
            </Link>
            <Link href="/runs" className="flex items-center gap-3 text-zinc-400 hover:text-emerald-400 transition-colors">
              <GitMerge size={18} /> Workflows
            </Link>
            <Link href="/audits" className="flex items-center gap-3 text-zinc-400 hover:text-emerald-400 transition-colors">
              <ShieldAlert size={18} /> Governance Audits
            </Link>
          </nav>
        </aside>
        <main className="flex-1 p-8 overflow-auto h-screen bg-black">
          {children}
        </main>
      </body>
    </html>
  );
}
