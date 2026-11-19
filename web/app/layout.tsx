import type { Metadata } from "next";

import { CommandPalette } from "@/components/command-palette";
import { Nav } from "@/components/nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "Swing & Long-Term",
  description:
    "Paper-trading research platform for Indian equities. Four strategies, four independent verdicts.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <Nav />
        <CommandPalette />
        <main className="flex-1">{children}</main>
        <footer className="border-t border-border-subtle bg-surface-raised px-6 py-4">
          <p className="mx-auto max-w-6xl text-xs text-text-muted">
            Paper trading only — no orders are ever placed. Insights are delivered in-app;
            there is no email, push or messaging channel.
          </p>
        </footer>
      </body>
    </html>
  );
}
