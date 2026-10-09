FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py listener.py moderator.py carbon_bot.py ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
