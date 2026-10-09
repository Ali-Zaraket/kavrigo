import type { Metadata } from "next";
import { HostedProviders, Providers } from "@/components/session";
import { Shell } from "@/components/shell";
import { webAuthConfiguration } from "@/lib/auth-config";

export const metadata: Metadata = {
  title: "Kavrigo · Paper workspace",
  robots: { index: false, follow: false },
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return webAuthConfiguration().mode === "clerk" ? (
    <HostedProviders>
      <Shell>{children}</Shell>
    </HostedProviders>
  ) : (
    <Providers>
      <Shell>{children}</Shell>
    </Providers>
  );
}
