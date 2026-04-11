# Vanilla Playwright fetcher for the Ranger (public tier).
# DO NOT add stealth patches, patchright, or Camoufox to this image.
# Sites with anti-bot protection SHOULD return 403 — that's by design.

FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app
COPY app.py .

# hadolint ignore=DL3013,SC2102
# DL3013: floor-pinned via `>=` is the intended strategy here.
# SC2102: uvicorn[standard] is pip extras syntax, not a char range.
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32"

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
