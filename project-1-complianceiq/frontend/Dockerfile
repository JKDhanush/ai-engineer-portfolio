# Multi-stage build: install + build with the full toolchain, ship only the standalone server (~150 MB image).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
# Only used by the dev-style /api rewrite; in production Caddy routes /api before it reaches Next.js
ARG API_URL=http://api:8000
ENV API_URL=$API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
