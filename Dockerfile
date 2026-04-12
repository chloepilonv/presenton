FROM python:3.11-slim-bookworm

# Install system deps. Skip libreoffice (we don't use PDF export — Drive handles PDFs).
# Skip ollama (we use OpenAI). Use --no-install-recommends to keep image slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    curl \
    ca-certificates \
    fontconfig \
    chromium \
    zstd \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV APP_DATA_DIRECTORY=/app_data
ENV TEMP_DIRECTORY=/tmp/presenton
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Install FastAPI deps. Skip docling/torch (we only send text, never documents).
# Install + cleanup in a single layer to avoid bloat.
RUN pip install --no-cache-dir \
      alembic aiohttp aiomysql aiosqlite asyncpg "fastapi[standard]" \
      pathvalidate pdfplumber chromadb sqlmodel \
      anthropic google-genai openai fastmcp dirtyjson \
      "python-pptx>=1.0.2" redis nltk pytest \
    && pip cache purge || true

# Stub out docling at import time (not installed — we only use text content)
RUN mkdir -p /usr/local/lib/python3.11/site-packages/docling/datamodel && \
    printf '' > /usr/local/lib/python3.11/site-packages/docling/__init__.py && \
    printf 'class DocumentConverter:\n    def __init__(self,**kw):pass\n    def convert(self,*a,**kw):raise RuntimeError("docling not installed")\nclass PdfFormatOption:\n    def __init__(self,**kw):pass\nclass WordFormatOption:\n    def __init__(self,**kw):pass\nclass PowerpointFormatOption:\n    def __init__(self,**kw):pass\n' > /usr/local/lib/python3.11/site-packages/docling/document_converter.py && \
    printf '' > /usr/local/lib/python3.11/site-packages/docling/datamodel/__init__.py && \
    printf 'class PdfPipelineOptions:\n    do_ocr = False\n' > /usr/local/lib/python3.11/site-packages/docling/datamodel/pipeline_options.py && \
    printf 'from enum import Enum\nclass InputFormat(str,Enum):\n    PPTX="pptx"\n    PDF="pdf"\n    DOCX="docx"\n' > /usr/local/lib/python3.11/site-packages/docling/datamodel/base_models.py

# Install Next.js deps
WORKDIR /app/servers/nextjs
COPY servers/nextjs/package.json servers/nextjs/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Copy and build the Next.js app
COPY servers/nextjs/ /app/servers/nextjs/
RUN npm run build && \
    # Trim dev deps after build
    npm prune --production && \
    rm -rf /root/.npm

WORKDIR /app

# Copy FastAPI code
COPY servers/fastapi/ ./servers/fastapi/
COPY start.js LICENSE NOTICE ./

# Copy nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Ensure data directories exist (Railway volume mounts /app_data at runtime)
RUN mkdir -p /app_data /tmp/presenton

EXPOSE 80

CMD ["node", "/app/start.js"]
