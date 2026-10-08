FROM node:22-alpine AS build
WORKDIR /app
# The backend's address inside the Docker network — baked into the built
# server bundle's route-proxy config (vite.config.ts). Not a browser-facing
# URL; the browser only ever calls its own origin's /api/* (see lib/api.js).
ARG BACKEND_INTERNAL_URL=http://backend:5000
ENV BACKEND_INTERNAL_URL=${BACKEND_INTERNAL_URL}
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/.output ./.output
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
