package loadgen

import (
	"context"
	"errors"
	"testing"

	"github.com/PUDAP/puda/apps/loadgen/internal/config"
	"github.com/nats-io/nats.go"
)

func TestConnectionCount(t *testing.T) {
	tests := []struct {
		mode        config.Mode
		edges       int
		connections int
		want        int
	}{
		{config.ModeFullFidelity, 100, 8, 100},
		{config.ModeMultiplexed, 100, 8, 8},
		{config.ModeMultiplexed, 3, 8, 3},
	}
	for _, tt := range tests {
		cfg := config.Config{Mode: tt.mode, Edges: tt.edges, Connections: tt.connections}
		if got := connectionCount(cfg); got != tt.want {
			t.Fatalf("connectionCount(%+v)=%d want=%d", cfg, got, tt.want)
		}
	}
}

func TestScenarioCapabilities(t *testing.T) {
	if !needsConsumers(config.ScenarioConsumers) || !needsConsumers(config.ScenarioSoak) {
		t.Fatal("consumer scenarios must create consumers")
	}
	if needsConsumers(config.ScenarioTelemetry) {
		t.Fatal("telemetry must not create consumers")
	}
	if !needsHeartbeat(config.ScenarioHeartbeat) || !needsHeartbeat(config.ScenarioTelemetry) || !needsHeartbeat(config.ScenarioSoak) {
		t.Fatal("heartbeat-capable scenarios missing")
	}
	if needsFullTelemetry(config.ScenarioHeartbeat) || !needsFullTelemetry(config.ScenarioTelemetry) || !needsFullTelemetry(config.ScenarioSoak) {
		t.Fatal("full telemetry capabilities incorrect")
	}
}

func TestFetchErrorsAfterCancellationAreIgnored(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if shouldRecordFetchError(ctx, errors.New("connection closed")) {
		t.Fatal("shutdown fetch error should be ignored")
	}
	if shouldRecordFetchError(context.Background(), nats.ErrTimeout) {
		t.Fatal("normal fetch timeout should be ignored")
	}
	if !shouldRecordFetchError(context.Background(), errors.New("broken")) {
		t.Fatal("live fetch error should be recorded")
	}
}
