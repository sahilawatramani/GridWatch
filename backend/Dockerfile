FROM python:3.13-alpine3.22 AS build

WORKDIR /app

COPY requirements.txt .
RUN python -m venv /opt/venv \
	&& /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
	&& /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

FROM gcr.io/distroless/python3-debian13

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app

ENV PATH="/opt/venv/bin:${PATH}"

EXPOSE 8000

CMD ["/opt/venv/bin/python", "-c", "import os, uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))"]
