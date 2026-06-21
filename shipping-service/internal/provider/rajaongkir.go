package provider

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// ShippingProvider interface untuk multi-courier
type ShippingProvider interface {
	GetRates(ctx context.Context, origin, destination string, weight int) ([]Rate, error)
	Track(ctx context.Context, trackingNumber string) (*TrackingInfo, error)
	CreateShipment(ctx context.Context, req CreateShipmentReq) (*CreateShipmentResp, error)
}

type Rate struct {
	Courier     string `json:"courier"`
	CourierName string `json:"courier_name"`
	Service     string `json:"service"`
	ServiceName string `json:"service_name"`
	Cost        int    `json:"cost"`
	ETD         string `json:"etd"`
	Currency    string `json:"currency"`
}

type TrackingInfo struct {
	TrackingNumber string         `json:"tracking_number"`
	Status         string         `json:"status"`
	History        []TrackingEvent `json:"history"`
}

type TrackingEvent struct {
	Timestamp time.Time `json:"timestamp"`
	Status    string    `json:"status"`
	Location  string    `json:"location"`
	Note      string    `json:"note"`
}

type CreateShipmentReq struct {
	OrderID        string `json:"order_id"`
	Origin         string `json:"origin"`
	Destination    string `json:"destination"`
	Weight         int    `json:"weight"`
	Courier        string `json:"courier"`
	Service        string `json:"service"`
	RecipientName  string `json:"recipient_name"`
	RecipientPhone string `json:"recipient_phone"`
	RecipientAddr  string `json:"recipient_address"`
}

type CreateShipmentResp struct {
	TrackingNumber string `json:"tracking_number"`
	Provider       string `json:"provider"`
}

// RajaOngkirProvider implements ShippingProvider untuk RajaOngkir
type RajaOngkirProvider struct {
	apiKey  string
	baseURL string
	client  *http.Client
}

func NewRajaOngkir(apiKey, baseURL string) *RajaOngkirProvider {
	return &RajaOngkirProvider{
		apiKey:  apiKey,
		baseURL: baseURL,
		client:  &http.Client{Timeout: 10 * time.Second},
	}
}

func (r *RajaOngkirProvider) GetRates(ctx context.Context, origin, destination string, weight int) ([]Rate, error) {
	if r.apiKey == "" {
		return r.mockRates(origin, destination, weight), nil
	}

	url := fmt.Sprintf("%s/cost", r.baseURL)
	payload := map[string]any{
		"origin":      origin,
		"destination": destination,
		"weight":      weight,
		"courier":     "jne:pos:tiki:sicepat:jnt",
	}
	body, _ := json.Marshal(payload)

	req, _ := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(body))
	req.Header.Set("key", r.apiKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := r.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("rajaongkir returned %d", resp.StatusCode)
	}

	var result struct {
		Rajaongkir struct {
			Results []struct {
				Code string `json:"code"`
				Name string `json:"name"`
				Costs []struct {
					Service     string `json:"service"`
					Description string `json:"description"`
					Cost []struct {
						Value int    `json:"value"`
						Etd   string `json:"etd"`
					} `json:"cost"`
				} `json:"costs"`
			} `json:"results"`
		} `json:"rajaongkir"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, err
	}

	var rates []Rate
	for _, r := range result.Rajaongkir.Results {
		for _, c := range r.Costs {
			if len(c.Cost) > 0 {
				rates = append(rates, Rate{
					Courier:     r.Code,
					CourierName: r.Name,
					Service:     c.Service,
					ServiceName: c.Description,
					Cost:        c.Cost[0].Value,
					ETD:         c.Cost[0].Etd,
					Currency:    "IDR",
				})
			}
		}
	}
	return rates, nil
}

func (r *RajaOngkirProvider) Track(ctx context.Context, trackingNumber string) (*TrackingInfo, error) {
	return &TrackingInfo{
		TrackingNumber: trackingNumber,
		Status:         "in_transit",
		History: []TrackingEvent{
			{
				Timestamp: time.Now().Add(-24 * time.Hour),
				Status:    "picked_up",
				Location:  "Jakarta Sorting Center",
				Note:      "Package picked up by courier",
			},
			{
				Timestamp: time.Now().Add(-12 * time.Hour),
				Status:    "in_transit",
				Location:  "Transit Hub",
				Note:      "Package in transit",
			},
		},
	}, nil
}

func (r *RajaOngkirProvider) CreateShipment(ctx context.Context, req CreateShipmentReq) (*CreateShipmentResp, error) {
	return &CreateShipmentResp{
		TrackingNumber: fmt.Sprintf("TRK%s%d", req.OrderID[:8], time.Now().Unix()),
		Provider:       "rajaongkir",
	}, nil
}

func (r *RajaOngkirProvider) mockRates(origin, destination string, weight int) []Rate {
	baseCost := 8000 + (weight/1000)*2000
	return []Rate{
		{Courier: "jne", CourierName: "JNE", Service: "REG", ServiceName: "Regular", Cost: baseCost, ETD: "2-3", Currency: "IDR"},
		{Courier: "jne", CourierName: "JNE", Service: "YES", ServiceName: "Next Day", Cost: baseCost * 2, ETD: "1", Currency: "IDR"},
		{Courier: "jne", CourierName: "JNE", Service: "OKE", ServiceName: "Economy", Cost: baseCost - 2000, ETD: "4-5", Currency: "IDR"},
		{Courier: "pos", CourierName: "POS Indonesia", Service: "REG", ServiceName: "Regular", Cost: baseCost - 1000, ETD: "3-4", Currency: "IDR"},
		{Courier: "tiki", CourierName: "TIKI", Service: "REG", ServiceName: "Regular", Cost: baseCost + 1000, ETD: "2-3", Currency: "IDR"},
		{Courier: "sicepat", CourierName: "SiCepat", Service: "REG", ServiceName: "Regular", Cost: baseCost, ETD: "2-3", Currency: "IDR"},
		{Courier: "jnt", CourierName: "J&T Express", Service: "EZ", ServiceName: "Regular", Cost: baseCost - 500, ETD: "2-4", Currency: "IDR"},
	}
}
