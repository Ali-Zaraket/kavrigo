import type { NextConfig } from "next";
import { webAuthConfiguration } from "./src/lib/auth-config";

// NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is baked into a Next.js build. Refuse a
// staging/paper-prod build with development keys before an image can be promoted.
webAuthConfiguration();

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
