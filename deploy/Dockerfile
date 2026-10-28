# syntax=docker/dockerfile:1
# yovoice server image: CLI + MCP over stdio / HTTP.
# Build:  docker build -f deploy/Dockerfile -t yovoice .
# Run HTTP server:
#   docker run -d --name yovoice -p 8080:8080 \
#     -e YOVOICE_API_TOKEN="$(openssl rand -hex 32)" \
#     -v yovoice-data:/data yovoice serve --data-dir /data --listen 0.0.0.0:8080
# Run MCP over stdio (for Claude Desktop / Cursor / Claude Code):
#   docker run -i --rm -v yovoice-data:/data yovoice mcp --data-dir /data

FROM golang:1.26-bookworm AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 make gcc curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN python3 scripts/build-ffmpeg.py artifacts/tools \
    && go build -trimpath -o /out/yovoice ./cmd/yovoice \
    && cp -r artifacts/tools /out/tools

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /out/yovoice /usr/local/bin/yovoice
COPY --from=builder /out/tools /usr/local/bin/tools
VOLUME /data
EXPOSE 8080
ENTRYPOINT ["yovoice"]
# Default: HTTP + MCP server. Override with e.g. `mcp --data-dir /data` for stdio.
CMD ["serve", "--data-dir", "/data", "--listen", "0.0.0.0:8080"]
