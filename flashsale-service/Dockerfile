FROM golang:1.22-alpine AS builder
WORKDIR /app
RUN apk add --no-cache git ca-certificates
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags='-w -s' -o /app/bin/flashsale-service ./cmd

FROM alpine:3.19
RUN apk --no-cache add ca-certificates tzdata curl && adduser -D -u 10001 appuser
WORKDIR /app
COPY --from=builder /app/bin/flashsale-service /app/flashsale-service
USER appuser
EXPOSE 8015
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8015/health || exit 1
ENTRYPOINT ["/app/flashsale-service"]
