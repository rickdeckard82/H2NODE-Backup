FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# npm ci: instala exatamente o que está no lockfile (reprodutível) e falha se
# package.json e lock estiverem dessincronizados.
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
