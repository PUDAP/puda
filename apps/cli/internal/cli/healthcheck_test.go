package cli

import (
	"bytes"
	"errors"
	"strings"
	"testing"

	compatibility "github.com/PUDAP/puda"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
)

// Overall NATS status leads the default JSON; the advisory follows the NATS checks.
func TestWriteHealthReportJSONOrder(t *testing.T) {
	report := pudanats.HealthReport{
		Status:        pudanats.HealthOK,
		Compatibility: &pudanats.CompatibilityHealth{Status: "not_checked"},
	}
	var out bytes.Buffer
	if err := writeHealthReport(&out, report, false); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	if !strings.HasPrefix(text, "{\n  \"status\":") {
		t.Fatalf("status must be first: %s", text)
	}
	if strings.Index(text, `"compatibility":`) < strings.Index(text, `"gateways":`) {
		t.Fatalf("compatibility must follow gateways: %s", text)
	}
}

// Edges that replied are still evaluated when discovery also reported an error.
func TestHealthCompatibilityKeepsRespondersOnDiscoveryError(t *testing.T) {
	pongs := []pudanats.PingResult{{MachineID: "edge", Status: "pong", SDKVersion: "0.0.22"}}
	result := evaluateHealthCompatibility(pongs, errors.New("nats: permissions violation"))
	if len(result.Machines) != 1 || result.Machines[0].MachineID != "edge" {
		t.Fatalf("responders dropped: %+v", result)
	}
	if result.Status == "not_checked" || result.Reason != "discovery_incomplete" || !strings.Contains(result.Error, "permissions violation") {
		t.Fatalf("partial discovery not identified: %+v", result)
	}
}

func TestHealthcheckHumanCompatibilityAndWriteFailures(t *testing.T) {
	report := pudanats.HealthReport{Status: "unhealthy", JetStream: pudanats.JetStreamHealth{Status: "not_checked", Reason: "nats_unreachable"}, Compatibility: &pudanats.CompatibilityHealth{Status: "unknown", AdvisoryOnly: true, Machines: []pudanats.MachineCompatibilityHealth{{MachineID: "edge", SDKVersion: "dev", Status: compatibility.Unknown}}}}
	var out bytes.Buffer
	if err := writeHealthReport(&out, report, true); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"jetstream: not_checked: nats_unreachable", "compatibility: unknown", "edge", "dev", "advisory only"} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("missing %q: %s", want, out.String())
		}
	}
	// Human output has two return paths (with and without gateways); JSON one.
	for _, gateways := range [][]pudanats.GatewayHealth{nil, {{Status: "unhealthy", JetStream: pudanats.JetStreamHealth{Status: "not_checked", Reason: "nats_unreachable"}}}} {
		report.Gateways = gateways
		for _, human := range []bool{false, true} {
			if err := writeHealthReport(failedDiscoveryWriter{}, report, human); err == nil || !strings.Contains(err.Error(), "write failed") {
				t.Errorf("human=%t gateways=%d lost output failure: %v", human, len(gateways), err)
			}
		}
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
		JetStream: pudanats.JetStreamHealth{Status: "failed", Reason: "jetstream_error", Error: "JetStream not enabled"},
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
