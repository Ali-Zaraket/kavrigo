# Build from the repository root. The public Clerk key and web origin are baked into
# Next.js; the matching secret key is supplied only as a BuildKit secret and again at runtime.
FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS build

WORKDIR /app
RUN npm install --global pnpm@11.19.0
COPY kavrigo-platform/apps/web/package.json kavrigo-platform/apps/web/pnpm-lock.yaml kavrigo-platform/apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY kavrigo-platform/apps/web/ ./

ARG KAVRIGO_ENV
ARG KAVRIGO_WEB_AUTH_PROVIDER
ARG KAVRIGO_WEB_ORIGIN
ARG NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV KAVRIGO_ENV=${KAVRIGO_ENV} \
    KAVRIGO_WEB_AUTH_PROVIDER=${KAVRIGO_WEB_AUTH_PROVIDER} \
    KAVRIGO_WEB_ORIGIN=${KAVRIGO_WEB_ORIGIN} \
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=${NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY}

# The app's config refuses hosted builds missing a production Clerk key or HTTPS origin.
# BuildKit keeps the secret out of Docker layers; never pass CLERK_SECRET_KEY as an ARG.
RUN --mount=type=secret,id=clerk_secret_key \
    if [ -f /run/secrets/clerk_secret_key ]; then \
      export CLERK_SECRET_KEY="$(cat /run/secrets/clerk_secret_key)"; \
    fi; \
    pnpm build

FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS runtime
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN groupadd --gid 10001 kavrigo && useradd --uid 10001 --gid 10001 --create-home kavrigo
COPY --from=build --chown=kavrigo:kavrigo /app/.next/standalone ./
COPY --from=build --chown=kavrigo:kavrigo /app/.next/static ./.next/static
COPY --from=build --chown=kavrigo:kavrigo /app/public ./public
USER 10001:10001
EXPOSE 3000
CMD ["node", "server.js"]
