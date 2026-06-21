// Package observability provides shared error reporting for Go services.
package observability

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"runtime"
	"runtime/debug"
	"time"
)

// ErrorReporter pushes errors to the centralized audit-service.
type ErrorReporter struct {
	endpoint    string
	serviceName string
	environment string
	hostname    string
	client      *http.Client
}

// New creates an ErrorReporter from environment variables.
func New() *ErrorReporter {
	endpoint := os.Getenv("AUDIT_SERVICE_URL")
	if endpoint == "" {
		endpoint = "http://audit-service:8006"
	}
	svc := os.Getenv("SERVICE_NAME")
	if svc == "" {
		svc = "unknown"
	}
	env := os.Getenv("ENVIRONMENT")
	if env == "" {
		env = "development"
	}
	hostname, _ := os.Hostname()
	return &ErrorReporter{
		endpoint:    endpoint,
		serviceName: svc,
		environment: env,
		hostname:    hostname,
		client:      &http.Client{Timeout: 2 * time.Second},
	}
}

// Report sends an error to audit-service.
func (r *ErrorReporter) Report(
	ctx context.Context,
	err any,
	context map[string]any,
	requestID string,
	correlationID string,
	userID string,
) {
	if context == nil {
		context = map[string]any{}
	}
	context["hostname"] = r.hostname
	context["goroutines"] = runtime.NumGoroutine()

	payload := map[string]any{
		"service":        r.serviceName,
		"environment":    r.environment,
		"level":          "error",
		"error_type":     fmt.Sprintf("%T", err),
		"message":        fmt.Sprintf("%v", err),
		"stack_trace":    string(debug.Stack()),
		"context":        context,
		"request_id":     requestID,
		"correlation_id": correlationID,
		"user_id":        userID,
	}

	body, _ := json.Marshal(payload)
	req, _ := http.NewRequestWithContext(ctx, "POST",
		r.endpoint+"/api/v1/internal/errors", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")

	resp, err := r.client.Do(req)
	if err != nil {
		return
	}
	resp.Body.Close()
}

var defaultReporter = New()

// ReportError is a convenience function using the default reporter.
func ReportError(ctx context.Context, err any, context map[string]any) {
	defaultReporter.Report(ctx, err, context, "", "", "")
}

// ReportErrorWithRequest reports with request context.
func ReportErrorWithRequest(ctx context.Context, err any, context map[string]any,
	requestID, correlationID, userID string) {
	defaultReporter.Report(ctx, err, context, requestID, correlationID, userID)
}
