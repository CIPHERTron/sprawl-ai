import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sprawl AI — Secret Posture Management",
  description:
    "Detect exposed secrets, visualize their blast radius, and rotate them safely.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-background antialiased">{children}</body>
    </html>
  );
}
