package logger

import (
	"fmt"
	"os"
	"strings"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

type Logger struct {
	*zap.SugaredLogger
}

func New(environment string) (*Logger, error) {
	var cfg zap.Config
	if environment == "production" {
		cfg = zap.NewProductionConfig()
		cfg.Level = zap.NewAtomicLevelAt(zapcore.InfoLevel)
	} else {
		cfg = zap.NewDevelopmentConfig()
		cfg.Level = zap.NewAtomicLevelAt(zapcore.DebugLevel)
		cfg.EncoderConfig.EncodeLevel = zapcore.CapitalColorLevelEncoder
	}

	// JSON encoder in production for log aggregation
	if environment == "production" {
		cfg.Encoding = "json"
		cfg.EncoderConfig.TimeKey = "timestamp"
		cfg.EncoderConfig.EncodeTime = zapcore.ISO8601TimeEncoder
	}

	l, err := cfg.Build(zap.AddCallerSkip(1), zap.AddStacktrace(zapcore.ErrorLevel))
	if err != nil {
		return nil, fmt.Errorf("build logger: %w", err)
	}
	return &Logger{l.Sugar()}, nil
}

// With returns a logger with additional context fields
func (l *Logger) With(fields ...any) *Logger {
	return &Logger{l.SugaredLogger.With(fields...)}
}

// RedactStr replaces sensitive values for logging
func RedactStr(key, val string) string {
	if isSensitiveKey(key) && len(val) > 4 {
		return strings.Repeat("*", len(val)-4) + val[len(val)-4:]
	}
	return val
}

func isSensitiveKey(k string) bool {
	lk := strings.ToLower(k)
	switch lk {
	case "password", "passwd", "secret", "token", "access_token", "refresh_token",
		"api_key", "apikey", "authorization", "auth", "credit_card", "card_number",
		"cvv", "ssn", "private_key", "session_id":
		return true
	}
	return false
}

// Fatal logs error and exits
func (l *Logger) Fatal(msg string, err error, fields ...any) {
	allFields := append([]any{"error", err}, fields...)
	l.SugaredLogger.Fatalw(msg, allFields...)
	os.Exit(1)
}
