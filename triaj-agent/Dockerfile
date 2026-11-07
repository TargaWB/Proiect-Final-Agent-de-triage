FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed STATE_DIR=/app/state
WORKDIR /app

COPY requirements.txt requirements-eval.txt ./
ARG INSTALL_EVAL=true
RUN pip install -r requirements.txt && \
    if [ "$INSTALL_EVAL" = "true" ]; then pip install -r requirements-eval.txt; fi

# modelul de embedding intra in imagine: pornire rapida, fara descarcare la runtime
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY agent ./agent
COPY api ./api
COPY ui ./ui
COPY scripts ./scripts
COPY data/tickets.csv data/test_tickets.csv ./data/
COPY tests ./tests
COPY pytest.ini ./
COPY .streamlit ./.streamlit

EXPOSE 8000 8501 8502
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
