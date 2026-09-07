package nats

import (
	"strings"
	"testing"
	"time"
)

func TestSplitServerURLsTrimsAndDeduplicates(t *testing.T) {
	got := SplitServerURLs(" nats://a:4222,nats://b:4222, nats://a:4222 , ")
	want := []string{"nats://a:4222", "nats://b:4222"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("got=%v want=%v", got, want)
	}
}

func TestCheckHealthRejectsEmptyServerList(t *testing.T) {
	if _, err := CheckHealth("  ,  ", "", time.Second); err == nil {
		t.Fatal("expected error for empty server list")
	}
}

func TestCheckHealthUnreachableIsUnhealthy(t *testing.T) {
	report, err := CheckHealth("nats://127.0.0.1:1", "", 200*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != HealthUnhealthy {
		t.Fatalf("status=%s", report.Status)
	}
	if report.Cluster.Configured != 1 || report.Cluster.Reachable != 0 {
		t.Fatalf("cluster=%+v", report.Cluster)
	}
	if len(report.Servers) != 1 || report.Servers[0].Status != "error" || report.Servers[0].Error == "" {
		t.Fatalf("servers=%+v", report.Servers)
	}
	if report.JetStream.OK || report.JetStream.Error == "" {
		t.Fatalf("jetstream=%+v", report.JetStream)
	}
}

func TestSummarizeHealthOK(t *testing.T) {
	report := summarizeHealth([]ServerHealth{
		{URL: "nats://a:4222", Status: "ok", Cluster: "puda", DiscoveredServers: []string{"nats://b:4222"}},
		{URL: "nats://b:4222", Status: "ok", Cluster: "puda"},
	}, JetStreamHealth{OK: true, Streams: 4})
	if report.Status != HealthOK {
		t.Fatalf("status=%s", report.Status)
	}
	if report.Cluster.Name != "puda" || report.Cluster.Reachable != 2 || report.Cluster.Configured != 2 {
		t.Fatalf("cluster=%+v", report.Cluster)
	}
	if strings.Join(report.Cluster.Discovered, ",") != "nats://a:4222,nats://b:4222" {
		t.Fatalf("discovered=%v", report.Cluster.Discovered)
	}
}

func TestSummarizeHealthDegradedWhenNodeDown(t *testing.T) {
	report := summarizeHealth([]ServerHealth{
		{URL: "nats://a:4222", Status: "ok", Cluster: "puda"},
		{URL: "nats://b:4222", Status: "error", Error: "timeout"},
	}, JetStreamHealth{OK: true})
	if report.Status != HealthDegraded {
		t.Fatalf("status=%s", report.Status)
	}
	if report.Cluster.Reachable != 1 {
		t.Fatalf("reachable=%d", report.Cluster.Reachable)
	}
}

func TestSummarizeHealthUnhealthyWhenJetStreamFails(t *testing.T) {
	report := summarizeHealth([]ServerHealth{
		{URL: "nats://a:4222", Status: "ok", Cluster: "puda"},
	}, JetStreamHealth{Error: "JetStream not enabled"})
	if report.Status != HealthUnhealthy {
		t.Fatalf("status=%s", report.Status)
	}
}

func TestSummarizeHealthDegradedWhenClusterNamesDisagree(t *testing.T) {
	report := summarizeHealth([]ServerHealth{
		{URL: "nats://a:4222", Status: "ok", Cluster: "alpha"},
		{URL: "nats://b:4222", Status: "ok", Cluster: "beta"},
	}, JetStreamHealth{OK: true})
	if report.Status != HealthDegraded {
		t.Fatalf("status=%s", report.Status)
	}
	if report.Cluster.Name != "alpha,beta" {
		t.Fatalf("cluster name=%q", report.Cluster.Name)
	}
}

func TestSummarizeGatewaysGroupsByRemoteCluster(t *testing.T) {
	gateways := summarizeGateways([]probe{
		{server: ServerHealth{URL: "nats://b1:4222", Status: "ok", Cluster: "imre"}, js: JetStreamHealth{OK: true, Streams: 3}},
		{server: ServerHealth{URL: "nats://b2:4222", Status: "ok", Cluster: "imre"}, js: JetStreamHealth{OK: true, Streams: 3}},
		{server: ServerHealth{URL: "nats://c1:4222", Status: "ok", Cluster: "ntu"}, js: JetStreamHealth{OK: true, Streams: 1}},
	})
	if len(gateways) != 2 {
		t.Fatalf("gateways=%d", len(gateways))
	}
	if gateways[0].Cluster != "imre" || gateways[0].Status != HealthOK || gateways[0].Configured != 2 || gateways[0].JetStream.Streams != 3 {
		t.Fatalf("imre=%+v", gateways[0])
	}
	if gateways[1].Cluster != "ntu" || gateways[1].Status != HealthOK || gateways[1].Configured != 1 {
		t.Fatalf("ntu=%+v", gateways[1])
	}
}

func TestSummarizeGatewaysAttachesUnknownFailuresToSingleRemote(t *testing.T) {
	gateways := summarizeGateways([]probe{
		{server: ServerHealth{URL: "nats://b1:4222", Status: "ok", Cluster: "imre"}, js: JetStreamHealth{OK: true}},
		{server: ServerHealth{URL: "nats://b2:4222", Status: "error", Error: "timeout"}},
	})
	if len(gateways) != 1 || gateways[0].Cluster != "imre" || gateways[0].Status != HealthDegraded || gateways[0].Reachable != 1 {
		t.Fatalf("gateways=%+v", gateways)
	}
}

func TestApplyGatewayStatusDoesNotTreatRemoteNameAsLocalSplit(t *testing.T) {
	report := summarizeHealth([]ServerHealth{
		{URL: "nats://a:4222", Status: "ok", Cluster: "bears"},
	}, JetStreamHealth{OK: true})
	report.Gateways = summarizeGateways([]probe{
		{server: ServerHealth{URL: "nats://b:4222", Status: "ok", Cluster: "imre"}, js: JetStreamHealth{OK: true}},
	})
	report = applyGatewayStatus(report)
	if report.Status != HealthOK {
		t.Fatalf("status=%s", report.Status)
	}
}

func TestApplyGatewayStatusDegradesWhenRemoteDown(t *testing.T) {
	report := summarizeHealth([]ServerHealth{
		{URL: "nats://a:4222", Status: "ok", Cluster: "bears"},
	}, JetStreamHealth{OK: true})
	report.Gateways = summarizeGateways([]probe{
		{server: ServerHealth{URL: "nats://b:4222", Status: "error", Error: "timeout"}},
	})
	report = applyGatewayStatus(report)
	if report.Status != HealthDegraded {
		t.Fatalf("status=%s", report.Status)
	}
	if len(report.Gateways) != 1 || report.Gateways[0].Status != HealthUnhealthy {
		t.Fatalf("gateways=%+v", report.Gateways)
	}
}

func TestCheckHealthUnreachableGatewayIsDegraded(t *testing.T) {
	report, err := CheckHealth("nats://127.0.0.1:1", "nats://127.0.0.1:2", 200*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != HealthUnhealthy {
		t.Fatalf("local down should stay unhealthy, got %s", report.Status)
	}
}
