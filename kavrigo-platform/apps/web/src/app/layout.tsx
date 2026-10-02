import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { HostedProviders, Providers } from "@/components/session";
import { Shell } from "@/components/shell";
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
  const authMode = process.env.KAVRIGO_WEB_AUTH_PROVIDER ?? "dev";
  if (authMode !== "dev" && authMode !== "clerk") {
    throw new Error("KAVRIGO_WEB_AUTH_PROVIDER must be dev or clerk");
  }
  const hosted = authMode === "clerk";
  if (
    hosted &&
    (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ||
      !process.env.CLERK_SECRET_KEY)
  ) {
    throw new Error(
      "Hosted sign-in requires Clerk publishable and secret keys",
    );
  }
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        {hosted ? (
          <ClerkProvider>
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
