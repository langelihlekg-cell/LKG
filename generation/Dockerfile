# GPU worker image. Base includes CUDA runtime for Depth Anything V2 inference.
# For serverless GPU deployment (Phase 5: RunPod Serverless / Modal), this
# same image is what you point their container config at.
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3-pip ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY generation/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY generation/ ./generation/
COPY qc/ ./qc/
COPY api/ ./api/

# Pre-fetch model weights at build time so cold starts don't pay the download
# cost — remove this line if you'd rather fetch on first request.
RUN python3 -c "from transformers import pipeline; pipeline(task='depth-estimation', model='depth-anything/Depth-Anything-V2-Small-hf')" || true

CMD ["celery", "-A", "api.tasks", "worker", "--loglevel=info", "--concurrency=1"]
