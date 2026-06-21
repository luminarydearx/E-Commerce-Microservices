package config

import (
	"fmt"
	"os"
	"strconv"

	"gopkg.in/yaml.v3"
)

type Config struct {
	ServiceName   string `yaml:"service_name"`
	Environment   string `yaml:"environment"`
	Port          string `yaml:"port"`
	MaxRequestSize int64 `yaml:"max_request_size"`

	JWT struct {
		PublicKeyPath string `yaml:"public_key_path"`
		Issuer        string `yaml:"issuer"`
	} `yaml:"jwt"`

	RedisURL string `yaml:"redis_url"`

	OtelEndpoint string `yaml:"otel_endpoint"`

	AllowedOrigins []string `yaml:"allowed_origins"`

	RateLimit RateLimitConfig `yaml:"rate_limit"`

	Services map[string]string `yaml:"services"` // service_name -> base URL
}

type RateLimitConfig struct {
	GlobalRPS       int     `yaml:"global_rps"`
	GlobalBurst     int     `yaml:"global_burst"`
	AuthRPS         int     `yaml:"auth_rps"`
	AuthBurst       int     `yaml:"auth_burst"`
	PublicRPS       int     `yaml:"public_rps"`
	PublicBurst     int     `yaml:"public_burst"`
	CheckoutRPS     int     `yaml:"checkout_rps"`
	CheckoutBurst   int     `yaml:"checkout_burst"`
	AdminRPS        int     `yaml:"admin_rps"`
	AdminBurst      int     `yaml:"admin_burst"`
	PerUserRPS      int     `yaml:"per_user_rps"`
	PerUserBurst    int     `yaml:"per_user_burst"`
	BlockThreshold  int     `yaml:"block_threshold"` // ban IP after N violations
}

func Load() (*Config, error) {
	cfg := &Config{
		ServiceName:    getEnv("SERVICE_NAME", "api-gateway"),
		Environment:    getEnv("ENVIRONMENT", "development"),
		Port:           getEnv("PORT", "8080"),
		MaxRequestSize: getEnvInt64("MAX_REQUEST_SIZE", 10*1024*1024),
		RedisURL:       getEnv("REDIS_URL", "redis://localhost:6379/0"),
		OtelEndpoint:   getEnv("OTEL_ENDPOINT", "localhost:4317"),
		AllowedOrigins: getEnvSlice("ALLOWED_ORIGINS", []string{"http://localhost:3000"}),
	}

	cfg.JWT.PublicKeyPath = getEnv("JWT_PUBLIC_KEY_PATH", "/app/keys/public.pem")
	cfg.JWT.Issuer = getEnv("JWT_ISSUER", "auth-service")

	cfg.RateLimit.GlobalRPS = getEnvInt("RATE_LIMIT_GLOBAL_RPS", 1000)
	cfg.RateLimit.GlobalBurst = getEnvInt("RATE_LIMIT_GLOBAL_BURST", 2000)
	cfg.RateLimit.AuthRPS = getEnvInt("RATE_LIMIT_AUTH_RPS", 5)
	cfg.RateLimit.AuthBurst = getEnvInt("RATE_LIMIT_AUTH_BURST", 10)
	cfg.RateLimit.PublicRPS = getEnvInt("RATE_LIMIT_PUBLIC_RPS", 100)
	cfg.RateLimit.PublicBurst = getEnvInt("RATE_LIMIT_PUBLIC_BURST", 200)
	cfg.RateLimit.CheckoutRPS = getEnvInt("RATE_LIMIT_CHECKOUT_RPS", 10)
	cfg.RateLimit.CheckoutBurst = getEnvInt("RATE_LIMIT_CHECKOUT_BURST", 20)
	cfg.RateLimit.AdminRPS = getEnvInt("RATE_LIMIT_ADMIN_RPS", 100)
	cfg.RateLimit.AdminBurst = getEnvInt("RATE_LIMIT_ADMIN_BURST", 200)
	cfg.RateLimit.PerUserRPS = getEnvInt("RATE_LIMIT_PER_USER_RPS", 100)
	cfg.RateLimit.PerUserBurst = getEnvInt("RATE_LIMIT_PER_USER_BURST", 150)
	cfg.RateLimit.BlockThreshold = getEnvInt("RATE_LIMIT_BLOCK_THRESHOLD", 100)

	// Service URLs
	cfg.Services = map[string]string{
		"auth-service":         getEnv("AUTH_SERVICE_URL", "http://localhost:8001"),
		"catalog-service":      getEnv("CATALOG_SERVICE_URL", "http://localhost:8002"),
		"order-service":        getEnv("ORDER_SERVICE_URL", "http://localhost:8003"),
		"payment-service":      getEnv("PAYMENT_SERVICE_URL", "http://localhost:8004"),
		"notification-service": getEnv("NOTIFICATION_SERVICE_URL", "http://localhost:8005"),
		"audit-service":        getEnv("AUDIT_SERVICE_URL", "http://localhost:8006"),
	}

	// Validate
	if err := cfg.validate(); err != nil {
		return nil, fmt.Errorf("config validation: %w", err)
	}
	return cfg, nil
}

func (c *Config) validate() error {
	if c.Port == "" {
		return fmt.Errorf("port is required")
	}
	if c.Environment != "development" && c.Environment != "staging" && c.Environment != "production" {
		return fmt.Errorf("invalid environment: %s", c.Environment)
	}
	if c.MaxRequestSize < 1024 {
		return fmt.Errorf("max_request_size too small: %d", c.MaxRequestSize)
	}
	if c.RateLimit.GlobalRPS < 1 {
		return fmt.Errorf("global_rps must be positive")
	}
	if len(c.AllowedOrigins) == 0 {
		return fmt.Errorf("allowed_origins cannot be empty")
	}
	return nil
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
		var result []string
		if err := yaml.Unmarshal([]byte(v), &result); err != nil {
			return fallback
		}
		return result
	}
	return fallback
}
