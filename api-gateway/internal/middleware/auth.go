package middleware

import (
	"context"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"ecommerce/api-gateway/pkg/logger"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
)

// JWTVerifier memverifikasi JWT token dengan RS256
type JWTVerifier struct {
	publicKey *rsa.PublicKey
	issuer    string
	redis     *redis.Client
	log       *logger.Logger
}

var (
	once     sync.Once
	loadErr  error
	verifier *JWTVerifier
)

func NewJWTVerifier(publicKeyPath string, log *logger.Logger) (*JWTVerifier, error) {
	keyBytes, err := os.ReadFile(publicKeyPath)
	if err != nil {
		return nil, fmt.Errorf("read public key: %w", err)
	}
	block, _ := pem.Decode(keyBytes)
	if block == nil {
		return nil, fmt.Errorf("failed to decode PEM block")
	}

	pub, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		// Try PKCS1
		pub1, err1 := x509.ParsePKCS1PublicKey(block.Bytes)
		if err1 != nil {
			return nil, fmt.Errorf("parse public key: %w (pkix: %v, pkcs1: %v)", err, err, err1)
		}
		pub = pub1
	}

	rsaPub, ok := pub.(*rsa.PublicKey)
	if !ok {
		return nil, fmt.Errorf("not an RSA public key")
	}

	return &JWTVerifier{
		publicKey: rsaPub,
		issuer:    "auth-service",
		redis:     redis.NewClient(&redis.Options{Addr: "localhost:6379"}),
		log:       log,
	}, nil
}

// Claims custom JWT claims
type Claims struct {
	UserID      string   `json:"sub"`
	Roles       []string `json:"roles"`
	Permissions []string `json:"permissions"`
	jwt.RegisteredClaims
}

// Authenticate middleware untuk verify JWT
func Authenticate(v *JWTVerifier, log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		authHeader := c.GetHeader("Authorization")
		if authHeader == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error":   "unauthorized",
				"message": "missing authorization header",
			})
			return
		}

		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error":   "unauthorized",
				"message": "invalid authorization header format",
			})
			return
		}

		tokenStr := strings.TrimSpace(parts[1])
		if tokenStr == "" {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error":   "unauthorized",
				"message": "empty token",
			})
			return
		}

		claims := &Claims{}
		token, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (any, error) {
			if _, ok := t.Method.(*jwt.SigningMethodRSA); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
			}
			return v.publicKey, nil
		}, jwt.WithIssuer(v.issuer), jwt.WithValidMethods([]string{"RS256"}))

		if err != nil || !token.Valid {
			log.Warn("invalid token", "error", err, "ip", c.ClientIP())
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error":   "unauthorized",
				"message": "invalid or expired token",
			})
			return
		}

		// Check JTI blacklist (revoked token)
		jti := claims.ID
		if jti != "" {
			ctx, cancel := context.WithTimeout(c.Request.Context(), 100*time.Millisecond)
			defer cancel()
			exists, err := v.redis.Exists(ctx, "jwt:blacklist:"+jti).Result()
			if err == nil && exists > 0 {
				c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
					"error":   "unauthorized",
					"message": "token has been revoked",
				})
				return
			}
		}

		// Inject user context
		c.Set("user_id", claims.UserID)
		c.Set("user_roles", claims.Roles)
		c.Set("user_permissions", claims.Permissions)
		c.Request.Header.Set("X-User-Id", claims.UserID)
		c.Request.Header.Set("X-User-Roles", strings.Join(claims.Roles, ","))

		c.Next()
	}
}

// RequestID middleware untuk inject request ID
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := c.GetHeader("X-Request-Id")
		if rid == "" {
			rid = uuid.NewString()
		}
		c.Set("request_id", rid)
		c.Writer.Header().Set("X-Request-Id", rid)
		c.Request.Header.Set("X-Request-Id", rid)
		c.Next()
	}
}

// CorrelationID middleware untuk trace antar service
func CorrelationID() gin.HandlerFunc {
	return func(c *gin.Context) {
		cid := c.GetHeader("X-Correlation-Id")
		if cid == "" {
			cid = c.GetString("request_id")
		}
		c.Set("correlation_id", cid)
		c.Writer.Header().Set("X-Correlation-Id", cid)
		c.Request.Header.Set("X-Correlation-Id", cid)
		c.Next()
	}
}
