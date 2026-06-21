package config

import (
	"fmt"
	"os"
)

type Config struct {
	Environment   string
	Port          string
	DatabaseURL   string
	RedisAddr     string
	QueueMaxSize  int
	QueueSlotTTL  int // seconds — how long a queue slot is valid
}

func Load() (*Config, error) {
	cfg := &Config{
		Environment:  getEnv("ENVIRONMENT", "development"),
		Port:         getEnv("PORT", "8015"),
		DatabaseURL:  getEnv("DATABASE_URL", ""),
		RedisAddr:    getEnv("REDIS_ADDR", "redis:6379"),
		QueueMaxSize: 100000,
		QueueSlotTTL: 300,
	}
	if cfg.DatabaseURL == "" {
		return nil, fmt.Errorf("DATABASE_URL required")
	}
	return cfg, nil
}

func getEnv(k, fb string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return fb
}
