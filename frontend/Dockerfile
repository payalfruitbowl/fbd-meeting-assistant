# Simple dev mode Dockerfile for Next.js frontend
FROM node:18-alpine

WORKDIR /app

# Install dependencies
RUN apk add --no-cache libc6-compat

# Copy package files
COPY package*.json ./
RUN npm ci

# Copy application code
COPY . .

# Expose port
EXPOSE 3000

# Run in dev mode with hostname binding
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]

