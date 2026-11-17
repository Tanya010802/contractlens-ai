FROM node:22-alpine AS dashboard
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY contractlens ./contractlens
COPY examples ./examples
COPY --from=dashboard /app/dist ./frontend/dist
RUN useradd --system contractlens
USER contractlens
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "contractlens.api:app", "--host", "0.0.0.0", "--port", "8000"]
