import type { Metadata } from "next";
import { Archivo, IBM_Plex_Mono, Instrument_Serif } from "next/font/google";

import "./globals.css";

const instrumentSerif = Instrument_Serif({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-instrument-serif",
  display: "swap",
});

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "GENESIS — Autonomous AI Research Laboratory",
  description:
    "GENESIS autonomously searches literature, forms hypotheses, designs experiments, executes code in a secure sandbox, evaluates results, and selects the next experiment.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body
        className={`${instrumentSerif.variable} ${archivo.variable} ${plexMono.variable}`}
      >
        {children}
      </body>
    </html>
  );
}
