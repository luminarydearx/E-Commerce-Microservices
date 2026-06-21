package logger

import (
	"fmt"
	"os"
	"strings"

	"github.com/sirupsen/logrus"
)

type Logger struct {
	*logrus.Entry
}

func New(environment string) *Logger {
	l := logrus.New()
	if environment == "production" {
		l.SetFormatter(&logrus.JSONFormatter{
			TimestampFormat: "2006-01-02T15:04:05.000Z07:00",
		})
		l.SetLevel(logrus.InfoLevel)
	} else {
		l.SetFormatter(&logrus.TextFormatter{
			FullTimestamp: true,
			ForceColors:   true,
		})
		l.SetLevel(logrus.DebugLevel)
	}
	l.SetOutput(os.Stdout)
	return &Logger{logrus.NewEntry(l)}
}

func (l *Logger) Sync() error { return nil }

func (l *Logger) With(fields ...any) *Logger {
	m := make(map[string]any)
	for i := 0; i+1 < len(fields); i += 2 {
		key, _ := fields[i].(string)
		m[key] = fields[i+1]
	}
	return &Logger{l.Entry.WithFields(m)}
}

// Redact returns masked value for sensitive keys
func Redact(key, val string) string {
	if isSensitive(key) && len(val) > 4 {
		return strings.Repeat("*", len(val)-4) + val[len(val)-4:]
	}
	return val
}

func isSensitive(k string) bool {
	switch strings.ToLower(k) {
	case "password", "secret", "token", "authorization", "api_key", "credit_card":
		return true
	}
	return false
}

// Fatal logs error and exits
func (l *Logger) Fatal(msg string, err error, fields ...any) {
	allFields := append([]any{"error", err}, fields...)
	l.With(allFields...).Error(msg)
	os.Exit(1)
}

// Override Error method to accept variadic fields
func (l *Logger) Error(msg string, err error, fields ...any) {
	allFields := append([]any{"error", err}, fields...)
	l.With(allFields...).Entry.Error(msg)
}

func (l *Logger) Warn(msg string, fields ...any) {
	l.With(fields...).Entry.Warn(msg)
}

func (l *Logger) Info(msg string, fields ...any) {
	l.With(fields...).Entry.Info(msg)
}

// Unused but kept
var _ = fmt.Sprintf
