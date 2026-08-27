package config

import (
	"testing"
	"time"
)

func TestParseDefaults(t *testing.T) {
	cfg, err := Parse(nil)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Edges != 1000 || cfg.Prefix != "load" || cfg.StartIndex != 1 {
		t.Fatalf("unexpected identity defaults: %+v", cfg)
	}
	if cfg.Mode != ModeFullFidelity || cfg.Scenario != ScenarioConnections {
		t.Fatalf("unexpected mode defaults: %+v", cfg)
	}
	if len(cfg.NATSServers) != 1 || cfg.NATSServers[0] != "nats://localhost:4222" {
		t.Fatalf("unexpected servers: %v", cfg.NATSServers)
	}
	if cfg.MetricsAddress != "127.0.0.1:9090" || cfg.QueueFetchWait != 30*time.Second || !cfg.CleanupConsumers || cfg.CommandInterval != 0 {
		t.Fatalf("unsafe runtime defaults: %+v", cfg)
	}
}

func TestParseCanKeepConsumersForOfflineTesting(t *testing.T) {
	cfg, err := Parse([]string{"--cleanup-consumers=false"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.CleanupConsumers {
		t.Fatal("cleanup should be disabled")
	}
}

func TestParseExplicitValues(t *testing.T) {
	cfg, err := Parse([]string{"--edges", "200", "--start-index", "101", "--prefix", "bench", "--mode", "multiplexed", "--connections", "8", "--scenario", "telemetry", "--nats-servers", "nats://a:4222,nats://b:4222", "--duration", "2m", "--ramp-duration", "30s"})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Edges != 200 || cfg.StartIndex != 101 || cfg.Prefix != "bench" {
		t.Fatalf("unexpected IDs: %+v", cfg)
	}
	if cfg.Mode != ModeMultiplexed || cfg.Connections != 8 || cfg.Scenario != ScenarioTelemetry {
		t.Fatalf("unexpected runtime config: %+v", cfg)
	}
	if cfg.Duration != 2*time.Minute || cfg.RampDuration != 30*time.Second {
		t.Fatalf("unexpected durations: %+v", cfg)
	}
}

func TestValidateRejectsInvalidSettings(t *testing.T) {
	tests := [][]string{{"--edges", "0"}, {"--start-index", "0"}, {"--mode", "invalid"}, {"--scenario", "invalid"}, {"--mode", "multiplexed", "--connections", "0"}, {"--heartbeat-interval", "0s"}, {"--queue-fetch-wait", "0s"}, {"--command-interval", "-1s"}, {"--scenario", "telemetry", "--command-interval", "5s"}}
	for _, args := range tests {
		if _, err := Parse(args); err == nil {
			t.Fatalf("Parse(%v) succeeded, want error", args)
		}
	}
}

func TestRedactedServersHideCredentials(t *testing.T) {
	got := RedactedServers([]string{"nats://user:secret@nats.example:4222", "nats://plain:4222"})
	if got[0] != "nats://REDACTED@nats.example:4222" || got[1] != "nats://plain:4222" {
		t.Fatalf("redacted=%v", got)
	}
}
