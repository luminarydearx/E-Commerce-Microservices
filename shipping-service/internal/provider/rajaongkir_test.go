package provider

import (
	"testing"
)

func TestRajaOngkirMockRates(t *testing.T) {
	r := NewRajaOngkir("", "https://api.rajaongkir.com/starter")
	rates := r.mockRates("152", "445", 1000)

	if len(rates) == 0 {
		t.Fatal("mockRates should return at least some rates")
	}

	// Verify structure
	for _, rate := range rates {
		if rate.Courier == "" {
			t.Error("rate.Courier should not be empty")
		}
		if rate.CourierName == "" {
			t.Error("rate.CourierName should not be empty")
		}
		if rate.Service == "" {
			t.Error("rate.Service should not be empty")
		}
		if rate.Cost <= 0 {
			t.Errorf("rate.Cost should be positive, got %d", rate.Cost)
		}
		if rate.Currency != "IDR" {
			t.Errorf("rate.Currency should be IDR, got %s", rate.Currency)
		}
	}
}

func TestRajaOngkirMockRatesWeightBased(t *testing.T) {
	r := NewRajaOngkir("", "")

	// Heavier package should cost more
	rates1kg := r.mockRates("152", "445", 1000)
	rates5kg := r.mockRates("152", "445", 5000)

	if len(rates1kg) == 0 || len(rates5kg) == 0 {
		t.Fatal("mockRates should return rates")
	}

	// First rate (JNE REG) should be more expensive for 5kg
	if rates5kg[0].Cost <= rates1kg[0].Cost {
		t.Errorf("heavier package should cost more: 5kg=%d, 1kg=%d",
			rates5kg[0].Cost, rates1kg[0].Cost)
	}
}

func TestRajaOngkirTrack(t *testing.T) {
	r := NewRajaOngkir("", "")
	info, err := r.Track(nil, "TRK123456")
	if err != nil {
		t.Fatalf("Track failed: %v", err)
	}
	if info.TrackingNumber != "TRK123456" {
		t.Errorf("TrackingNumber = %q, want TRK123456", info.TrackingNumber)
	}
	if info.Status != "in_transit" {
		t.Errorf("Status = %q, want in_transit", info.Status)
	}
	if len(info.History) == 0 {
		t.Error("History should not be empty")
	}
}

func TestRajaOngkirCreateShipment(t *testing.T) {
	r := NewRajaOngkir("", "")
	req := CreateShipmentReq{
		OrderID: "order-12345678",
		Origin:  "152",
		Destination: "445",
		Weight:  1000,
		Courier: "jne",
		Service: "REG",
	}
	resp, err := r.CreateShipment(nil, req)
	if err != nil {
		t.Fatalf("CreateShipment failed: %v", err)
	}
	if resp.TrackingNumber == "" {
		t.Error("TrackingNumber should not be empty")
	}
	if resp.Provider != "rajaongkir" {
		t.Errorf("Provider = %q, want rajaongkir", resp.Provider)
	}
}

func TestRateStruct(t *testing.T) {
	rate := Rate{
		Courier:     "jne",
		CourierName: "JNE",
		Service:     "REG",
		ServiceName: "Regular",
		Cost:        18000,
		ETD:         "2-3",
		Currency:    "IDR",
	}
	if rate.Courier != "jne" {
		t.Error("Courier mismatch")
	}
	if rate.Cost != 18000 {
		t.Error("Cost mismatch")
	}
}

func TestCreateShipmentReqStruct(t *testing.T) {
	req := CreateShipmentReq{
		OrderID:        "order-123",
		Origin:         "152",
		Destination:    "445",
		Weight:         1000,
		Courier:        "jne",
		Service:        "REG",
		RecipientName:  "John Doe",
		RecipientPhone: "+6281234567890",
		RecipientAddr:  "Jl. Sudirman No. 1",
	}
	if req.OrderID != "order-123" {
		t.Error("OrderID mismatch")
	}
	if req.Weight != 1000 {
		t.Error("Weight mismatch")
	}
}
