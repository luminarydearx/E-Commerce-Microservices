package handler

import (
	"net/url"

	"github.com/redis/go-redis/v9"
)

func redisOptions(redisURL string) *redis.Options {
	u, err := url.Parse(redisURL)
	if err != nil {
		return &redis.Options{Addr: "localhost:6379"}
	}
	opts := &redis.Options{
		Addr: u.Host,
	}
	if u.User != nil {
		opts.Password, _ = u.User.Password()
	}
	if u.Path != "" && len(u.Path) > 1 {
		opts.DB = 0
	}
	return opts
}
