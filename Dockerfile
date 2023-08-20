FROM python:3.11.3-alpine

# Set environment variable
ENV CRON "*/25 * * * *"

# Install dependencies
RUN apk update && \
    apk add --no-cache \
    curl \
    git \
    wget \
    bash \
    build-base \
    libffi-dev \
    openssl-dev \
    sqlite-dev \
    tk-dev \
    gdbm-dev \
    libc-dev \
    bzip2-dev \
    zlib-dev \
    nodejs \
    npm

# Install pm2
RUN npm install -g pm2

# Install Papillon
RUN mkdir -p /hosting/papillon && \
    curl -o /hosting/papillon/start.sh https://raw.githubusercontent.com/PapillonApp/papillon-python/development/papillon_start.sh && \
    chmod +x /hosting/papillon/start.sh

CMD cd /hosting/papillon/ && \
    pm2 start --name "Papillon" /hosting/papillon/start.sh --cron-restart="$CRON" && \
    pm2 logs
