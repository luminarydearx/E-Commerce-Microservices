package handler

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"ecommerce/api-gateway/internal/config"
	"ecommerce/api-gateway/pkg/logger"

	"github.com/gin-gonic/gin"
)

// ReverseProxy forwards request to backend service
type ReverseProxy struct {
	cfg     *config.Config
	log     *logger.Logger
	proxies map[string]*httputil.ReverseProxy
}

func NewReverseProxy(cfg *config.Config, log *logger.Logger) (*ReverseProxy, error) {
	rp := &ReverseProxy{
		cfg:     cfg,
		log:     log,
		proxies: make(map[string]*httputil.ReverseProxy),
	}
	for name, rawURL := range cfg.Services {
		u, err := url.Parse(rawURL)
		if err != nil {
			return nil, fmt.Errorf("parse service url %s: %w", name, err)
		}
		p := httputil.NewSingleHostReverseProxy(u)
		p.Transport = &http.Transport{
			MaxIdleConns:        100,
			MaxIdleConnsPerHost: 20,
			IdleConnTimeout:     90 * time.Second,
			ResponseHeaderTimeout: 30 * time.Second,
			ExpectContinueTimeout: 1 * time.Second,
		}
		p.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			log.Error("proxy error", err,
				"service", name,
				"path", r.URL.Path,
				"request_id", r.Header.Get("X-Request-Id"),
			)
			w.WriteHeader(http.StatusBadGateway)
			_, _ = w.Write([]byte(`{"error":"bad_gateway","message":"service unavailable"}`))
		}
		rp.proxies[name] = p
	}
	return rp, nil
}

// Handle returns gin handler that proxies to specified service with rewritten path
// pathPattern may contain `:id` style placeholders which are substituted from gin params
func (rp *ReverseProxy) Handle(serviceName, pathPattern string) gin.HandlerFunc {
	return func(c *gin.Context) {
		rp.doProxy(c, serviceName, pathPattern, nil)
	}
}

// HandleWithRole proxies only if user has one of allowed roles
func (rp *ReverseProxy) HandleWithRole(serviceName, pathPattern string, allowedRoles ...string) gin.HandlerFunc {
	return func(c *gin.Context) {
		roles, _ := c.Get("user_roles")
		userRoles, _ := roles.([]string)
		if !hasAnyRole(userRoles, allowedRoles) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":   "forbidden",
				"message": "insufficient role",
				"required_roles": allowedRoles,
			})
			return
		}
		// Inject role header for downstream
		c.Request.Header.Set("X-User-Roles", strings.Join(userRoles, ","))
		rp.doProxy(c, serviceName, pathPattern, nil)
	}
}

func (rp *ReverseProxy) doProxy(c *gin.Context, serviceName, pathPattern string, _ []string) {
	proxy, ok := rp.proxies[serviceName]
	if !ok {
		c.AbortWithStatusJSON(http.StatusBadGateway, gin.H{
			"error":   "service_not_found",
			"message": fmt.Sprintf("service %s not configured", serviceName),
		})
		return
	}

	// Rewrite path: substitute :param from gin context
	finalPath := pathPattern
	for _, p := range c.Params {
		finalPath = strings.ReplaceAll(finalPath, ":"+p.Key, p.Value)
	}

	// Preserve query string
	if c.Request.URL.RawQuery != "" {
		finalPath += "?" + c.Request.URL.RawQuery
	}

	// Modify request
	c.Request.URL.Path = finalPath
	c.Request.URL.RawPath = ""

	// Inject idempotency key check for POST/PUT on payment/order
	if (strings.Contains(serviceName, "payment") || strings.Contains(serviceName, "order")) &&
		(c.Request.Method == http.MethodPost || c.Request.Method == http.MethodPut) {
		idemKey := c.GetHeader("Idempotency-Key")
		if idemKey == "" {
			c.AbortWithStatusJSON(http.StatusBadRequest, gin.H{
				"error":   "missing_idempotency_key",
				"message": "Idempotency-Key header is required for this operation",
			})
			return
		}
	}

	// Add tracing header
	correlationID, _ := c.Get("correlation_id")
	c.Request.Header.Set("X-Correlation-Id", toString(correlationID))
	reqID, _ := c.Get("request_id")
	c.Request.Header.Set("X-Request-Id", toString(reqID))

	// Wrap response writer to capture status
	rw := &statusRecorder{ResponseWriter: c.Writer, status: 200}
	proxy.ServeHTTP(rw, c.Request)
}

type statusRecorder struct {
	gin.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
	return s.ResponseWriter.Write(b)
}

func hasAnyRole(userRoles, allowedRoles []string) bool {
	if len(allowedRoles) == 0 {
		return true
	}
	allowed := make(map[string]bool, len(allowedRoles))
	for _, r := range allowedRoles {
		allowed[r] = true
	}
	for _, r := range userRoles {
		if allowed[r] {
			return true
		}
	}
	return false
}

func toString(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprintf("%v", v)
}

// HealthCheck performs HTTP health check on a service
func (rp *ReverseProxy) HealthCheck(ctx context.Context, serviceName string) error {
	baseURL, ok := rp.cfg.Services[serviceName]
	if !ok {
		return fmt.Errorf("service not found")
	}
	client := &http.Client{Timeout: 2 * time.Second}
	req, err := http.NewRequestWithContext(ctx, "GET", baseURL+"/health", nil)
	if err != nil {
		return err
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode >= 400 {
		return fmt.Errorf("service unhealthy: status %d", resp.StatusCode)
	}
	return nil
}
