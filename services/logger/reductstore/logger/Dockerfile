FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md main.py reduct_client.py ./
RUN pip install --no-cache-dir .

CMD ["python", "-u", "main.py"]
