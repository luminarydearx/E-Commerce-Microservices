package middleware

import (
	"regexp"
	"strings"

	"ecommerce/api-gateway/pkg/logger"

	"github.com/gin-gonic/gin"
)

// WAF rules untuk block pattern malicious umum
var wafRules = []struct {
	Name    string
	Pattern *regexp.Regexp
}{
	// SQL Injection patterns
	{"sql_union", regexp.MustCompile(`(?i)\bunion\s+(all\s+)?select\b`)},
	{"sql_select_comment", regexp.MustCompile(`(?i)select.*from.*--`)},
	{"sql_drop", regexp.MustCompile(`(?i)\bdrop\s+(table|database)\b`)},
	{"sql_insert_meta", regexp.MustCompile(`(?i)insert\s+into.*values`)},
	{"sql_sleep", regexp.MustCompile(`(?i)sleep\s*\(\s*\d+\s*\)`)},
	{"sql_benchmark", regexp.MustCompile(`(?i)benchmark\s*\(`)},

	// XSS patterns
	{"xss_script", regexp.MustCompile(`(?i)<script[^>]*>`)},
	{"xss_javascript", regexp.MustCompile(`(?i)javascript:`)},
	{"xss_onerror", regexp.MustCompile(`(?i)onerror\s*=`)},
	{"xss_onload", regexp.MustCompile(`(?i)onload\s*=`)},
	{"xss_img", regexp.MustCompile(`(?i)<img[^>]+src[^>]+onerror`)},
	{"xss_svg", regexp.MustCompile(`(?i)<svg[^>]+onload`)},

	// Path traversal
	{"path_traversal", regexp.MustCompile(`\.\./|\.\.\\`)},

	// SSRF attempts (URL with internal IP)
	{"ssrf_localhost", regexp.MustCompile(`(?i)https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)`)},
	{"ssrf_internal", regexp.MustCompile(`(?i)https?://(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)`)},
	{"ssrf_metadata", regexp.MustCompile(`(?i)https?://169\.254\.169\.254`)},

	// Command injection
	{"cmd_injection", regexp.MustCompile(`(?i)(;\s*(cat|ls|rm|wget|curl|bash|sh)\s)|(\|\s*(cat|ls|rm|wget|curl|bash|sh)\s)|(\$\(|\` + "`" + `)`)},

	// XXE
	{"xxe", regexp.MustCompile(`(?i)<!ENTITY`)},

	// LDAP injection
	{"ldap_injection", regexp.MustCompile(`(?i)\)\(\|?\(.*\)\)`)},

	// NoSQL injection
	{"nosql_injection", regexp.MustCompile(`(?i)\$where|\$gt|\$lt|\$ne`)},

	// PHP injection
	{"php_injection", regexp.MustCompile(`(?i)<\?php`)},

	// Server-side template injection (basic)
	{"ssti", regexp.MustCompile(`(?i)\{\{.*\}\}|\{%.*%\}`)},
}

// WAF middleware checks request body, query, headers, path for malicious patterns
func WAF(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Check path
		if matched := checkWAF(c.Request.URL.Path); matched != "" {
			log.Warn("WAF: blocked request", "rule", matched, "ip", c.ClientIP(), "path", c.Request.URL.Path)
			c.AbortWithStatusJSON(403, gin.H{
				"error":   "forbidden",
				"message": "request blocked by security policy",
				"rule":    matched,
			})
			return
		}

		// Check query string
		if matched := checkWAF(c.Request.URL.RawQuery); matched != "" {
			log.Warn("WAF: blocked request", "rule", matched, "ip", c.ClientIP(), "query", c.Request.URL.RawQuery)
			c.AbortWithStatusJSON(403, gin.H{
				"error":   "forbidden",
				"message": "request blocked by security policy",
			})
			return
		}

		// Check headers (skip common safe ones)
		for k, v := range c.Request.Header {
			if k == "User-Agent" || k == "Accept" || k == "Accept-Encoding" || k == "Accept-Language" {
				continue
			}
			for _, val := range v {
				if matched := checkWAF(val); matched != "" {
					log.Warn("WAF: blocked header", "rule", matched, "ip", c.ClientIP(), "header", k)
					c.AbortWithStatusJSON(403, gin.H{
						"error":   "forbidden",
						"message": "request blocked by security policy",
					})
					return
				}
			}
		}

		c.Next()
	}
}

func checkWAF(input string) string {
	if len(input) > 1<<20 { // 1MB
		return "input_too_large"
	}
	for _, rule := range wafRules {
		if rule.Pattern.MatchString(input) {
			return rule.Name
		}
	}
	// Check for null bytes
	if strings.ContainsRune(input, 0) {
		return "null_byte"
	}
	return ""
}
