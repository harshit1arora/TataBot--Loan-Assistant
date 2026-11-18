# syntax=docker/dockerfile:1
# Build the SPA, then hand the static bundle to the gateway image.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_OIDC_ISSUER
ARG VITE_OIDC_CLIENT_ID
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
ENV OIDC_CONNECT_ORIGIN=""
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 8080
