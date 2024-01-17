FROM sanicframework/sanic:3.9-latest

# Set environment variable
ENV CRON "*/25 * * * *"
ENV DSN_URL "http://server:port"

WORKDIR /sanic

RUN pip freeze > requirements.txt
RUN pip install -r requirements.txt

EXPOSE 8000

CMD ["python", "server.py"]
