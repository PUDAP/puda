package cli

import (
	"bytes"
	"encoding/json"
	"errors"
	"strings"
	"testing"

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
	report := pudanats.HealthReport{Status: "unhealthy", JetStream: pudanats.JetStreamHealth{Status: "not_checked", Reason: "nats_unreachable"}, Compatibility: &pudanats.CompatibilityHealth{Status: "unsupported", AdvisoryOnly: true, SupportedProtocol: "1.x", Machines: []pudanats.MachineCompatibilityHealth{{MachineID: "edge", SDKVersion: "dev", Status: pudanats.ProtocolUnsupported}}}}
	var out bytes.Buffer
	if err := writeHealthReport(&out, report, true); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"jetstream: not_checked: nats_unreachable", "compatibility: unsupported", "supported_protocol=1.x", "edge: protocol=none", "dev", "advisory only"} {
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
		"endpoints: 1/2 reachable",
		"nats://a:4222: ok 1.250ms name=nats1 id=(none) cluster=puda js=true version=2.10.22",
		"nats://b:4222: failed: timeout",
		"cluster: puda\n",
		"jetstream: ok streams=4 consumers=2 memory=10 storage=20",
		"gateways: 1",
		"imre: degraded endpoints=1/2 reachable unique brokers=0",
		"nats://c:4222: ok 2.500ms name=nats-c id=(none) cluster=imre js=true version=2.10.22",
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
	if strings.Contains(output, "cluster:") {
		t.Fatalf("standalone server reported as a cluster: %s", output)
	}
}

// One standalone broker reachable through LAN and Tailscale is two endpoints and
// one broker, and is not presented as a cluster.
func TestWriteHealthReportHumanSeparatesEndpointsFromBrokers(t *testing.T) {
	report := pudanats.HealthReport{
		Status: pudanats.HealthOK,
		Servers: []pudanats.ServerHealth{
			{URL: "nats://192.168.1.10:4222", Status: "ok", Name: "nats", ID: "NSAME", JetStream: true},
			{URL: "nats://100.64.0.10:4222", Status: "ok", Name: "nats", ID: "NSAME", JetStream: true},
		},
		Cluster:   pudanats.ClusterHealth{Configured: 2, Reachable: 2, Brokers: []pudanats.BrokerHealth{{ID: "NSAME", Endpoints: []string{"nats://192.168.1.10:4222", "nats://100.64.0.10:4222"}}}, Discovered: []string{"nats://100.64.0.10:4222", "nats://192.168.1.10:4222"}},
		JetStream: pudanats.JetStreamHealth{Status: "ok", OK: true},
	}
	var buf bytes.Buffer
	if err := writeHealthReport(&buf, report, true); err != nil {
		t.Fatal(err)
	}
	output := buf.String()
	for _, want := range []string{"endpoints: 2/2 reachable", "unique brokers responding: 1\n", "id=NSAME"} {
		if !strings.Contains(output, want) {
			t.Fatalf("output missing %q: %s", want, output)
		}
	}
	for _, unwanted := range []string{"servers:", "cluster", "discovered"} {
		if strings.Contains(output, unwanted) {
			t.Fatalf("output contains %q: %s", unwanted, output)
		}
	}
}

// Endpoints without a server ID are reported, never grouped into a broker.
func TestWriteHealthReportHumanUnidentifiedEndpoints(t *testing.T) {
	report := pudanats.HealthReport{
		Status: pudanats.HealthOK,
		Servers: []pudanats.ServerHealth{
			{URL: "nats://a:4222", Status: "ok", Name: "nats"},
			{URL: "nats://b:4222", Status: "ok", Name: "nats"},
		},
		Cluster:   pudanats.ClusterHealth{Configured: 2, Reachable: 2, UnidentifiedEndpoints: 2},
		JetStream: pudanats.JetStreamHealth{Status: "ok", OK: true},
	}
	var buf bytes.Buffer
	if err := writeHealthReport(&buf, report, true); err != nil {
		t.Fatal(err)
	}
	if want := "unique brokers responding: 0 (2 reachable endpoint(s) reported no server ID; not counted)"; !strings.Contains(buf.String(), want) {
		t.Fatalf("output missing %q: %s", want, buf.String())
	}
}

// Existing JSON fields stay; brokers lists each server ID with its endpoints.
func TestWriteHealthReportJSONKeepsEndpointFieldsAndAddsBrokers(t *testing.T) {
	report := pudanats.HealthReport{
		Status:  pudanats.HealthOK,
		Cluster: pudanats.ClusterHealth{Configured: 2, Reachable: 2, Brokers: []pudanats.BrokerHealth{{ID: "NSAME", Endpoints: []string{"nats://a:4222", "nats://b:4222"}}}, Discovered: []string{"nats://a:4222", "nats://b:4222"}},
	}
	var out bytes.Buffer
	if err := writeHealthReport(&out, report, false); err != nil {
		t.Fatal(err)
	}
	var decoded struct {
		Servers []any `json:"servers"`
		Cluster struct {
			Configured *int     `json:"configured"`
			Reachable  *int     `json:"reachable"`
			Discovered []string `json:"discovered"`
			Brokers    []struct {
				ID        string   `json:"id"`
				Endpoints []string `json:"endpoints"`
			} `json:"brokers"`
		} `json:"cluster"`
	}
	if err := json.Unmarshal(out.Bytes(), &decoded); err != nil {
		t.Fatal(err)
	}
	c := decoded.Cluster
	if decoded.Servers == nil || c.Configured == nil || *c.Configured != 2 || c.Reachable == nil || *c.Reachable != 2 || len(c.Discovered) != 2 || len(c.Brokers) != 1 || c.Brokers[0].ID != "NSAME" || len(c.Brokers[0].Endpoints) != 2 {
		t.Fatalf("json=%s", out.String())
	}
}
