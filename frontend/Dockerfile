# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
COPY --from=build /app/dist/workflow-studio/browser /usr/share/nginx/html
ENV PORT=80 API_UPSTREAM=backend:8000 NGINX_ENVSUBST_FILTER="^(PORT|API_UPSTREAM)$"
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
