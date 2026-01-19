FROM python:3.14-slim

ADD sync.py /app/sync.py
ADD requirements.txt /app/requirements.txt

WORKDIR /app

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "sync.py"]
