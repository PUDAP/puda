FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

# Install anyio first with specific version to avoid conflicts
RUN pip install --no-cache-dir anyio==3.6.2

# Install core dependencies first
RUN pip install --no-cache-dir \
  mcp>=1.9.1 \
  fastmcp==2.8.1 \
  pydantic==2.7.4 \
  python-dotenv

# Install LangChain dependencies separately
RUN pip install --no-cache-dir \
  langchain-core \
  langchain-community \
  dashscope \
  langchain-deepseek \
  langchain-openai \
  langchain-anthropic

# Install visualization, data processing, and opentrons with specific versions
RUN pip install --no-cache-dir \
  matplotlib \
  pandas \
  numpy
#opentrons==6.3.1

# Choose a port
EXPOSE 8002

COPY services/opentron/server.py .
COPY llm_config.py .
COPY llm_config.json .
COPY .env .

CMD ["python", "server.py"]
