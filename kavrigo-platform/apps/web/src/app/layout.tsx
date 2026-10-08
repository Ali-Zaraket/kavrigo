import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { HostedProviders, Providers } from "@/components/session";
import { Shell } from "@/components/shell";
import { webAuthConfiguration } from "@/lib/auth-config";
import "./globals.css";

// Select the identity provider from the deployment's runtime configuration.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Kavrigo · Paper workspace",
  description: "Build AI trading agents you can test, inspect, and govern.",
  robots: { index: false, follow: false },
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
        {hosted ? (
          <ClerkProvider dynamic>
            <HostedProviders>
              <Shell>{children}</Shell>
            </HostedProviders>
          </ClerkProvider>
        ) : (
          <Providers>
            <Shell>{children}</Shell>
          </Providers>
        )}
      </body>
    </html>
  );
}
