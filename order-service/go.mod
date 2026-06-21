module ecommerce/order-service

go 1.22

require (
	github.com/gin-gonic/gin v1.10.0
	github.com/google/uuid v1.6.0
	github.com/jackc/pgx/v5 v5.6.0
	github.com/redis/go-redis/v9 v9.6.1
	github.com/sirupsen/logrus v1.9.3
	github.com/prometheus/client_golang v1.19.1
	go.opentelemetry.io/otel v1.27.0
	go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.27.0
	go.opentelemetry.io/otel/sdk v1.27.0
	go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin v0.52.0
	github.com/segmentio/kafka-go v0.4.47
	github.com/shopspring/decimal v1.4.0
	github.com/cenkalti/backoff/v4 v4.3.0
)
