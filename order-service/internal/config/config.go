package config

import (
	"fmt"
	"os"
	"strconv"
)

type Config struct {
	Environment    string
	Port           string
	DatabaseURL    string
	RedisURL       string
	KafkaBrokers   []string
	OtelEndpoint   string
	InternalToken  string
	CatalogSvcURL  string
	PaymentSvcURL  string
	AllowedOrigins []string

	MaxRequestSize int64

	Cart struct {
		MaxItems        int
		MaxQtyPerItem   int
		ExpirationHours int
	}

	Order struct {
		CancelWindowMinutes int
		MaxItemsPerOrder    int
	}
}

func Load() (*Config, error) {
	cfg := &Config{
		Environment:    getEnv("ENVIRONMENT", "development"),
		Port:           getEnv("PORT", "8003"),
		DatabaseURL:    getEnv("DATABASE_URL", ""),
		RedisURL:       getEnv("REDIS_URL", "redis://localhost:6379/2"),
		KafkaBrokers:   []string{getEnv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")},
		OtelEndpoint:   getEnv("OTEL_ENDPOINT", "localhost:4317"),
		InternalToken:  getEnv("INTERNAL_TOKEN", ""),
		CatalogSvcURL:  getEnv("CATALOG_SERVICE_URL", "http://localhost:8002"),
		PaymentSvcURL:  getEnv("PAYMENT_SERVICE_URL", "http://localhost:8004"),
		AllowedOrigins: getEnvSlice("ALLOWED_ORIGINS", []string{"http://localhost:3000"}),
		MaxRequestSize: getEnvInt64("MAX_REQUEST_SIZE", 1*1024*1024),
	}
	cfg.Cart.MaxItems = getEnvInt("CART_MAX_ITEMS", 100)
	cfg.Cart.MaxQtyPerItem = getEnvInt("CART_MAX_QTY_PER_ITEM", 99)
	cfg.Cart.ExpirationHours = getEnvInt("CART_EXPIRATION_HOURS", 168) // 7 hari
	cfg.Order.CancelWindowMinutes = getEnvInt("ORDER_CANCEL_WINDOW_MINUTES", 30)
	cfg.Order.MaxItemsPerOrder = getEnvInt("ORDER_MAX_ITEMS", 50)

	if cfg.DatabaseURL == "" {
		return nil, fmt.Errorf("DATABASE_URL is required")
	}
	if cfg.Environment != "development" && cfg.Environment != "staging" && cfg.Environment != "production" {
		return nil, fmt.Errorf("invalid environment: %s", cfg.Environment)
	}
	return cfg, nil
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if i, err := strconv.Atoi(v); err == nil {
			return i
		}
	}
	return fallback
}

func getEnvInt64(key string, fallback int64) int64 {
	if v := os.Getenv(key); v != "" {
		if i, err := strconv.ParseInt(v, 10, 64); err == nil {
			return i
		}
	}
	return fallback
}

func getEnvSlice(key string, fallback []string) []string {
	if v := os.Getenv(key); v != "" {
		var r []string
		for _, s := range splitCSV(v) {
			if s != "" {
				r = append(r, s)
			}
		}
		if len(r) > 0 {
			return r
		}
	}
	return fallback
}

func splitCSV(s string) []string {
	var result []string
	current := ""
	for _, c := range s {
		if c == ',' {
			result = append(result, current)
			current = ""
		} else {
			current += string(c)
		}
	}
	if current != "" {
		result = append(result, current)
	}
	return result
}
