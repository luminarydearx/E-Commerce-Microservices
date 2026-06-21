# Build stage
FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install git for private deps (if any)
RUN apk add --no-cache git ca-certificates

# Copy go mod files
COPY go.mod go.sum* ./

# Download dependencies
RUN go mod download

# Copy source
COPY . .

# Build static binary
RUN CGO_ENABLED=0 GOOS=linux go build \
    -ldflags='-w -s -extldflags "-static"' \
    -o /app/bin/api-gateway \
    ./cmd

# Runtime stage
FROM alpine:3.19

RUN apk --no-cache add ca-certificates tzdata curl && \
    adduser -D -u 10001 appuser

WORKDIR /app

COPY --from=builder /app/bin/api-gateway /app/api-gateway
COPY --from=builder /app/configs /app/configs

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["/app/api-gateway"]
