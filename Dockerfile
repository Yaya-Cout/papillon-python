FROM sanicframework/sanic:lts-py3.11
# Set environment variable
ENV CRON "*/25 * * * *"
ENV DSN_URL "http://server:port"

WORKDIR /sanic

COPY . .

RUN pip install -U https://github.com/bain3/pronotepy/archive/refs/heads/master.zip
RUN pip install lxml sentry-sdk redis sanic 

EXPOSE 8000

CMD ["python", "server.py"]
