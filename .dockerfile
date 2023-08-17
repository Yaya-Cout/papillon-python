FROM debian:bullseye-slim

# Set environment variable
ENV CRON="*/25 * * * *"
# remove all files /hosting even if there's nothing
RUN rm -rf /hosting

# Install dependencies & install Python 3.11.3
RUN apt-get update -y
RUN apt install curl git wget build-essential libncursesw5-dev libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev libffi-dev zlib1g-dev -y
RUN mkdir /install
RUN mkdir /install/python
RUN cd /install/python && wget https://www.python.org/ftp/python/3.11.3/Python-3.11.3.tgz
RUN tar -xvf /install/python/Python-3.11.3.tgz -C /install/python
RUN cd /install/python/Python-3.11.3 && ./configure --enable-optimizations
RUN cd /install/python/Python-3.11.3 && make altinstall
RUN pip3.11 install --upgrade pip

# Install Nodejs
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs

RUN exec bash
RUN npm install -g pm2

# Install Papillon
RUN mkdir -p /hosting/papillon
RUN curl -o /hosting/papillon/start.sh https://git.tryon-lab.fr/tryon/Papillon/raw/branch/main/papillon_start.sh
RUN chmod +x /hosting/papillon/start.sh
CMD cd /hosting/papillon/ && pm2 start --name "Papillon" /hosting/papillon/start.sh --cron-restart="$CRON" && pm2 logs
