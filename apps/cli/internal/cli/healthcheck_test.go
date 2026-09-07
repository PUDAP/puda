package cli

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
)

func TestHealthcheckCommandMetadata(t *testing.T) {
	if got, want := healthcheckCmd.Use, "healthcheck"; got != want {
		t.Fatalf("Use=%q want=%q", got, want)
	}
	if healthcheckCmd.Flags().Lookup("nats-servers") == nil {
		t.Fatal("healthcheck command must expose --nats-servers")
	}
	if healthcheckCmd.Flags().Lookup("human") == nil {
		t.Fatal("healthcheck command must expose --human")
	}
	if healthcheckCmd.Flags().Lookup("timeout") == nil {
		t.Fatal("healthcheck command must expose --timeout")
	}
	if healthcheckCmd.Flags().Lookup("gateway-servers") == nil {
		t.Fatal("healthcheck command must expose --gateway-servers")
	}
}

func TestWriteHealthReportJSONIsDefault(t *testing.T) {
	report := pudanats.HealthReport{
		Status: pudanats.HealthDegraded,
		Servers: []pudanats.ServerHealth{
			{URL: "nats://a:4222", Status: "ok", Name: "nats1", Cluster: "puda", JetStream: true, RTTMS: 1.25, Version: "2.10.22"},
			{URL: "nats://b:4222", Status: "error", Error: "timeout"},
		},
		Cluster: pudanats.ClusterHealth{
			Name:       "puda",
			Configured: 2,
			Reachable:  1,
			Discovered: []string{"nats://a:4222"},
		},
		JetStream: pudanats.JetStreamHealth{OK: true, Streams: 4, Consumers: 2, Memory: 10, Storage: 20},
		Gateways: []pudanats.GatewayHealth{
			{
				Cluster:    "imre",
				Status:     pudanats.HealthOK,
				Configured: 1,
				Reachable:  1,
				Servers:    []pudanats.ServerHealth{{URL: "nats://b:4222", Status: "ok", Cluster: "imre", JetStream: true}},
				JetStream:  pudanats.JetStreamHealth{OK: true, Streams: 3},
			},
		},
	}
	var buf bytes.Buffer
	if err := writeHealthReport(&buf, report, false); err != nil {
		t.Fatal(err)
	}
	var payload pudanats.HealthReport
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatalf("default output is not JSON: %v\n%s", err, buf.String())
	}
	if payload.Status != pudanats.HealthDegraded || payload.Cluster.Reachable != 1 || !payload.JetStream.OK {
		t.Fatalf("payload=%+v", payload)
	}
	if payload.Servers[0].Name != "nats1" || payload.Servers[1].Error != "timeout" {
		t.Fatalf("servers=%+v", payload.Servers)
	}
	if len(payload.Gateways) != 1 || payload.Gateways[0].Cluster != "imre" || payload.Gateways[0].JetStream.Streams != 3 {
		t.Fatalf("gateways=%+v", payload.Gateways)
	}
}

func TestWriteHealthReportHuman(t *testing.T) {
	report := pudanats.HealthReport{
		Status: pudanats.HealthDegraded,
		Servers: []pudanats.ServerHealth{
			{URL: "nats://a:4222", Status: "ok", Name: "nats1", Cluster: "puda", JetStream: true, RTTMS: 1.25, Version: "2.10.22"},
			{URL: "nats://b:4222", Status: "error", Error: "timeout"},
		},
		Cluster: pudanats.ClusterHealth{
			Name:       "puda",
			Configured: 2,
			Reachable:  1,
			Discovered: []string{"nats://a:4222"},
		},
		JetStream: pudanats.JetStreamHealth{OK: true, Streams: 4, Consumers: 2, Memory: 10, Storage: 20},
		Gateways: []pudanats.GatewayHealth{
			{
				Cluster:    "imre",
				Status:     pudanats.HealthDegraded,
				Configured: 2,
				Reachable:  1,
				Servers: []pudanats.ServerHealth{
					{URL: "nats://c:4222", Status: "ok", Name: "nats-c", Cluster: "imre", JetStream: true, RTTMS: 2.5, Version: "2.10.22"},
					{URL: "nats://d:4222", Status: "error", Error: "timeout"},
				},
				JetStream: pudanats.JetStreamHealth{OK: true, Streams: 3, Consumers: 1},
			},
		},
	}
	var buf bytes.Buffer
	if err := writeHealthReport(&buf, report, true); err != nil {
		t.Fatal(err)
	}
	output := buf.String()
	for _, want := range []string{
		"status: degraded",
		"servers: 1/2 reachable",
		"nats://a:4222: ok 1.250ms name=nats1 cluster=puda js=true version=2.10.22",
		"nats://b:4222: failed: timeout",
		"cluster: puda discovered=1",
		"jetstream: ok streams=4 consumers=2 memory=10 storage=20",
		"gateways: 1",
		"imre: degraded 1/2",
		"nats://c:4222: ok 2.500ms name=nats-c cluster=imre js=true version=2.10.22",
		"nats://d:4222: failed: timeout",
		"jetstream: ok streams=3 consumers=1 memory=0 storage=0",
	} {
		if !strings.Contains(output, want) {
			t.Fatalf("output missing %q: %s", want, output)
		}
	}
}

func TestWriteHealthReportHumanJetStreamFailure(t *testing.T) {
	report := pudanats.HealthReport{
		Status: pudanats.HealthUnhealthy,
		Servers: []pudanats.ServerHealth{
			{URL: "nats://a:4222", Status: "ok", Name: "nats1", JetStream: false, RTTMS: 0.5},
		},
		Cluster:   pudanats.ClusterHealth{Configured: 1, Reachable: 1, Discovered: []string{"nats://a:4222"}},
		JetStream: pudanats.JetStreamHealth{Error: "JetStream not enabled"},
	}
	var buf bytes.Buffer
	if err := writeHealthReport(&buf, report, true); err != nil {
		t.Fatal(err)
	}
	output := buf.String()
	if !strings.Contains(output, "status: unhealthy") || !strings.Contains(output, "jetstream: failed: JetStream not enabled") {
		t.Fatalf("output=%s", output)
	}
	if !strings.Contains(output, "cluster: (none) discovered=1") {
		t.Fatalf("output=%s", output)
	}
}
