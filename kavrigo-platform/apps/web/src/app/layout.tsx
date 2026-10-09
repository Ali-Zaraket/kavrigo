import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { webAuthConfiguration } from "@/lib/auth-config";
import "./globals.css";

// Select the identity provider from the deployment's runtime configuration.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Kavrigo · Build agents. Prove the edge.",
  description: "Build AI trading agents you can test, inspect, and govern.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { mode: authMode } = webAuthConfiguration();
  const hosted = authMode === "clerk";
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        {hosted ? <ClerkProvider dynamic>{children}</ClerkProvider> : children}
      </body>
    </html>
  );
}
