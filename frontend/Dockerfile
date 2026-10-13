# dev: the local docker-compose stack (Vite dev server). prod: the built site served by nginx (docker-compose.prod.yml).
FROM node:24-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npx", "vite", "--host", "0.0.0.0"]

FROM dev AS build
# Build-time settings, compiled into the public JS bundle: never pass secrets here.
# Same-site API by default: nginx proxies /api/ to Django.
ARG VITE_API_BASE_URL=/api
ARG VITE_APP_NAME="AS Hardware and Plywood"
ARG VITE_SUPPORT_PHONE=
ARG VITE_SUPPORT_WHATSAPP=
ARG VITE_SUPPORT_EMAIL=
ARG VITE_STORE_HOURS=
ARG VITE_MAP_TILE_URL=
ARG VITE_MAP_CENTER=
ARG VITE_OTP_LOGIN_ENABLED=false
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_APP_NAME=$VITE_APP_NAME VITE_SUPPORT_PHONE=$VITE_SUPPORT_PHONE \
    VITE_SUPPORT_WHATSAPP=$VITE_SUPPORT_WHATSAPP VITE_SUPPORT_EMAIL=$VITE_SUPPORT_EMAIL \
    VITE_STORE_HOURS=$VITE_STORE_HOURS VITE_MAP_TILE_URL=$VITE_MAP_TILE_URL VITE_MAP_CENTER=$VITE_MAP_CENTER \
    VITE_OTP_LOGIN_ENABLED=$VITE_OTP_LOGIN_ENABLED
RUN npm run build

FROM nginx:1.27-alpine AS prod
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf nginx/proxy-params.conf /etc/nginx/snippets/
COPY --from=build /app/dist /usr/share/nginx/html
# .htaccess is for Apache hosting only; nginx/default.conf carries the same rules.
RUN rm -f /usr/share/nginx/html/.htaccess
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
