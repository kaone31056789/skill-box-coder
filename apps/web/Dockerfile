# Built from the REPOSITORY ROOT as context (Railway builds the whole repo),
# so every path here is repo-relative rather than apps/web-relative.
FROM node:22-slim AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ ./
# NEXT_PUBLIC_* is inlined at build time, so the API URL must be known here --
# setting it only at runtime would leave the bundle pointing at localhost.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
# The standalone server reads PORT and HOSTNAME from the environment; it does
# not take a -p flag. Without HOSTNAME it binds the container's own hostname
# rather than all interfaces, and Railway's proxy gets a 502.
ENV NODE_ENV=production     HOSTNAME=0.0.0.0     PORT=3000
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
