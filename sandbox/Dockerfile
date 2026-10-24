FROM python:3.12-slim
RUN pip install --no-cache-dir "pandas>=2.2,<4" "numpy>=1.26,<3" "scikit-learn>=1.4,<2"
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
USER 65534:65534
