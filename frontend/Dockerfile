# Optional: only used by the local docker-compose stack. Production hosting serves the built dist/ folder.
FROM node:24-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npx", "vite", "--host", "0.0.0.0"]

FROM dev AS build
RUN npm run build
