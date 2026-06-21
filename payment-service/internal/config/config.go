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
	OrderSvcURL    string
	AllowedOrigins []string

	MidtransServerKey string
	MidtransBaseURL   string
	XenditSecretKey   string
	XenditBaseURL     string

	WebhookSecret string

	Withdrawal struct {
		MinAmount       int64
		AutoApproveMax  int64
	}

	MaxRequestSize int64
}

func Load() (*Config, error) {
	cfg := &Config{
		Environment:       getEnv("ENVIRONMENT", "development"),
		Port:              getEnv("PORT", "8004"),
		DatabaseURL:       getEnv("DATABASE_URL", ""),
		RedisURL:          getEnv("REDIS_URL", "redis://localhost:6379/3"),
		KafkaBrokers:      []string{getEnv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")},
		OtelEndpoint:      getEnv("OTEL_ENDPOINT", "localhost:4317"),
		InternalToken:     getEnv("INTERNAL_TOKEN", ""),
		OrderSvcURL:       getEnv("ORDER_SERVICE_URL", "http://localhost:8003"),
		AllowedOrigins:    getEnvSlice("ALLOWED_ORIGINS", []string{"http://localhost:3000"}),
		MidtransServerKey: getEnv("MIDTRANS_SERVER_KEY", ""),
		MidtransBaseURL:   getEnv("MIDTRANS_BASE_URL", "https://api.sandbox.midtrans.com/v2"),
		XenditSecretKey:   getEnv("XENDIT_SECRET_KEY", ""),
		XenditBaseURL:     getEnv("XENDIT_BASE_URL", "https://api.xendit.co"),
		WebhookSecret:     getEnv("WEBHOOK_SECRET", ""),
		MaxRequestSize:    getEnvInt64("MAX_REQUEST_SIZE", 1 * 1024 * 1024),
	}
	cfg.Withdrawal.MinAmount = getEnvInt64("WITHDRAWAL_MIN_AMOUNT", 10000)
	cfg.Withdrawal.AutoApproveMax = getEnvInt64("WITHDRAWAL_AUTO_APPROVE_MAX", 1000000)

	if cfg.DatabaseURL == "" {
		return nil, fmt.Errorf("DATABASE_URL is required")
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
		current := ""
		for _, c := range v {
			if c == ',' {
				if current != "" {
					r = append(r, current)
				}
				current = ""
			} else {
				current += string(c)
			}
		}
		if current != "" {
			r = append(r, current)
		}
		if len(r) > 0 {
			return r
		}
	}
	return fallback
}
