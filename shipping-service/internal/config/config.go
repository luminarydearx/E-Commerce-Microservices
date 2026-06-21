package config

import (
	"fmt"
	"os"
	"strconv"
)

type Config struct {
	Environment     string
	Port            string
	DatabaseURL     string
	RedisURL        string
	OtelEndpoint    string
	InternalToken   string
	RajaOngkirKey   string
	RajaOngkirURL   string
	CourierCacheTTL int // seconds
}

func Load() (*Config, error) {
	cfg := &Config{
		Environment:     getEnv("ENVIRONMENT", "development"),
		Port:            getEnv("PORT", "8010"),
		DatabaseURL:     getEnv("DATABASE_URL", ""),
		RedisURL:        getEnv("REDIS_URL", "redis://redis:6379/7"),
		OtelEndpoint:    getEnv("OTEL_ENDPOINT", "otel-collector:4317"),
		InternalToken:   getEnv("INTERNAL_TOKEN", ""),
		RajaOngkirKey:   getEnv("RAJA_ONGKIR_KEY", ""),
		RajaOngkirURL:   getEnv("RAJA_ONGKIR_URL", "https://api.rajaongkir.com/starter"),
		CourierCacheTTL: getEnvInt("COURIER_CACHE_TTL", 86400),
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

func getEnvInt(k string, fb int) int {
	if v := os.Getenv(k); v != "" {
		if i, err := strconv.Atoi(v); err == nil {
			return i
		}
	}
	return fb
}
