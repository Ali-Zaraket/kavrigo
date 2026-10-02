import { clerkMiddleware } from "@clerk/nextjs/server";
import {
  NextResponse,
  type NextFetchEvent,
  type NextRequest,
} from "next/server";

const hostedProxy =
  process.env.KAVRIGO_WEB_AUTH_PROVIDER === "clerk"
    ? clerkMiddleware({
        contentSecurityPolicy: {
          strict: true,
          directives: {
            "frame-ancestors": ["'none'"],
            "object-src": ["'none'"],
            "base-uri": ["'none'"],
          },
        },
      })
    : null;

/** Local development has no Clerk account; hosted deployments always run Clerk's proxy. */
export default function proxy(request: NextRequest, event: NextFetchEvent) {
  return hostedProxy ? hostedProxy(request, event) : NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
