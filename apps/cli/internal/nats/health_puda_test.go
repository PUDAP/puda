package nats

import (
	"errors"
	"strings"
	"testing"

	natsio "github.com/nats-io/nats.go"
)

type fakeStreams map[string]*natsio.StreamInfo

func (f fakeStreams) StreamInfo(name string, _ ...natsio.JSOpt) (*natsio.StreamInfo, error) {
	if info, ok := f[name]; ok {
		if info == nil {
			return nil, errors.New("permissions violation")
		}
		return info, nil
	}
	return nil, natsio.ErrStreamNotFound
}

func allStreams(replicas int, cluster *natsio.ClusterInfo) fakeStreams {
	streams := fakeStreams{}
	for _, spec := range pudaResourceSpecs {
		if !spec.required {
			continue
		}
		name := spec.name
		if spec.kind == "kv" {
			name = "KV_" + name
		}
		streams[name] = &natsio.StreamInfo{Config: natsio.StreamConfig{Name: name, Replicas: replicas}, Cluster: cluster}
	}
	return streams
}

func resourceByName(t *testing.T, puda PUDAHealth, name string) PUDAResource {
	t.Helper()
	for _, resource := range puda.Resources {
		if resource.Name == name {
			return resource
		}
	}
	t.Fatalf("resource %s missing from %+v", name, puda.Resources)
	return PUDAResource{}
}

func issueCodes(issues []HealthIssue) string {
	codes := make([]string, 0, len(issues))
	for _, issue := range issues {
		codes = append(codes, issue.Severity+":"+issue.Code+":"+issue.Target)
	}
	return strings.Join(codes, ",")
}

func okReport(clusterName string) HealthReport {
	return summarizeHealth([]ServerHealth{
		{URL: "nats://n1:4222", Status: "ok", ID: "N1", Cluster: clusterName, Version: "2.15.3", JetStream: true},
	}, JetStreamHealth{Status: "ok", OK: true})
}

func TestPUDAResourcesAllPresentStandaloneIsOK(t *testing.T) {
	report := applyPUDAHealth(okReport(""), checkPUDAResources(allStreams(1, nil)))
	if report.Status != HealthOK || report.PUDA.Status != "ok" {
		t.Fatalf("status=%s puda=%+v", report.Status, report.PUDA)
	}
	// Optional, on-demand resources may be missing without any issue.
	if resourceByName(t, report.PUDA, "LIVESTREAMS").Status != ResourceMissing {
		t.Fatal("LIVESTREAMS should be reported missing")
	}
	if issues := BuildIssues(report); len(issues) != 0 {
		t.Fatalf("issues=%s", issueCodes(issues))
	}
}

func TestPUDAResourceMissingIsUnhealthyWithSetupStep(t *testing.T) {
	streams := allStreams(1, nil)
	delete(streams, "COMMAND_QUEUE")
	delete(streams, "KV_MACHINE_STATE")
	report := applyPUDAHealth(okReport(""), checkPUDAResources(streams))
	if report.Status != HealthUnhealthy || report.PUDA.Reason != "resources_unavailable" {
		t.Fatalf("status=%s puda=%+v", report.Status, report.PUDA)
	}
	issues := BuildIssues(report)
	if got := issueCodes(issues); got != "unhealthy:puda_resources_missing:COMMAND_QUEUE,MACHINE_STATE" {
		t.Fatalf("issues=%s", got)
	}
	if !strings.Contains(issues[0].NextStep, "NATS_URL=nats://n1:4222 REPLICAS=1 ./setup_streams.sh") {
		t.Fatalf("next step lacks a runnable command: %s", issues[0].NextStep)
	}
	if issues[0].Source != "puda.resources[0],puda.resources[3]" {
		t.Fatalf("source=%s", issues[0].Source)
	}
}

func TestPUDAResourceSingleReplicaInClusterIsDegraded(t *testing.T) {
	cluster := &natsio.ClusterInfo{Leader: "nats1", Replicas: []*natsio.PeerInfo{}}
	report := applyPUDAHealth(okReport("puda"), checkPUDAResources(allStreams(1, cluster)))
	if report.Status != HealthDegraded || report.PUDA.Reason != "resources_degraded" {
		t.Fatalf("status=%s puda=%+v", report.Status, report.PUDA)
	}
	issues := BuildIssues(report)
	if len(issues) != 1 || issues[0].Code != "puda_resources_under_replicated" || strings.Count(issues[0].Target, ",") != 4 || !strings.Contains(issues[0].NextStep, "REPLICAS=3 ./setup_streams.sh") {
		t.Fatalf("issues=%s first=%+v", issueCodes(issues), issues[0])
	}
	// A standalone server with one replica is the normal single-node layout.
	if standalone := applyPUDAHealth(okReport(""), checkPUDAResources(allStreams(1, nil))); standalone.Status != HealthOK {
		t.Fatalf("standalone status=%s", standalone.Status)
	}
}

func TestPUDAResourceNoLeaderAndLaggingReplica(t *testing.T) {
	streams := allStreams(3, &natsio.ClusterInfo{Leader: "nats1", Replicas: []*natsio.PeerInfo{{Name: "nats2", Current: true}, {Name: "nats3", Current: true}}})
	streams["COMMAND_QUEUE"] = &natsio.StreamInfo{Config: natsio.StreamConfig{Replicas: 3}, Cluster: &natsio.ClusterInfo{Leader: "", Replicas: []*natsio.PeerInfo{{Name: "nats2", Offline: true}}}}
	streams["RESPONSE_QUEUE"] = &natsio.StreamInfo{Config: natsio.StreamConfig{Replicas: 3}, Cluster: &natsio.ClusterInfo{Leader: "nats1", Replicas: []*natsio.PeerInfo{{Name: "nats2", Current: true}, {Name: "nats3", Offline: true}}}}
	report := applyPUDAHealth(okReport("puda"), checkPUDAResources(streams))
	if report.Status != HealthUnhealthy {
		t.Fatalf("status=%s", report.Status)
	}
	lagging := resourceByName(t, report.PUDA, "RESPONSE_QUEUE")
	if lagging.Status != ResourceReplicaLagging || strings.Join(lagging.LaggingReplicas, ",") != "nats3" {
		t.Fatalf("lagging=%+v", lagging)
	}
	got := issueCodes(BuildIssues(report))
	if got != "unhealthy:puda_resource_no_leader:COMMAND_QUEUE,degraded:puda_resource_replica_lagging:RESPONSE_QUEUE" {
		t.Fatalf("issues=%s", got)
	}
	// One node behind on several resources is one issue listing them all.
	streams["KV_MACHINE_STATE"] = &natsio.StreamInfo{Config: natsio.StreamConfig{Replicas: 3}, Cluster: &natsio.ClusterInfo{Leader: "nats1", Replicas: []*natsio.PeerInfo{{Name: "nats2", Current: true}, {Name: "nats3", Offline: true}}}}
	report = applyPUDAHealth(okReport("puda"), checkPUDAResources(streams))
	issues := BuildIssues(report)
	if got := issueCodes(issues); got != "unhealthy:puda_resource_no_leader:COMMAND_QUEUE,degraded:puda_resource_replica_lagging:RESPONSE_QUEUE,MACHINE_STATE" || issues[1].Source != "puda.resources[1],puda.resources[3]" {
		t.Fatalf("issues=%s %+v", got, issues)
	}
}

func TestPUDAResourceUnreadableIsUnhealthyWithoutDuplicatingError(t *testing.T) {
	streams := allStreams(1, nil)
	streams["RESPONSE_QUEUE"] = nil
	report := applyPUDAHealth(okReport(""), checkPUDAResources(streams))
	issues := BuildIssues(report)
	if report.Status != HealthUnhealthy || len(issues) != 1 || issues[0].Code != "puda_resource_unreadable" {
		t.Fatalf("status=%s issues=%s", report.Status, issueCodes(issues))
	}
	if issues[0].Detail != "" || issues[0].Source != "puda.resources[1].error" {
		t.Fatalf("error text must stay in its field, issue=%+v", issues[0])
	}
}

func TestPUDAResourcesNotCheckedDoNotChangeStatus(t *testing.T) {
	report := summarizeHealth([]ServerHealth{{URL: "nats://n1:4222", Status: "ok", ID: "N1"}}, JetStreamHealth{Status: "failed", Reason: "jetstream_error", Error: "boom"})
	report = applyPUDAHealth(report, PUDAHealth{Status: "not_checked", Reason: "jetstream_unavailable"})
	if report.Status != HealthUnhealthy || report.PUDA.Status != "not_checked" || report.PUDA.Resources == nil {
		t.Fatalf("report=%+v", report)
	}
	if got := issueCodes(BuildIssues(report)); got != "unhealthy:jetstream_unavailable:local" {
		t.Fatalf("issues=%s", got)
	}
}

func TestConsumerLimitAdvisoryOnlyOn215(t *testing.T) {
	streams := allStreams(1, nil)
	streams["COMMAND_QUEUE"].State.Consumers = 950
	report := applyPUDAHealth(okReport(""), checkPUDAResources(streams))
	issues := BuildIssues(report)
	if report.Status != HealthOK || issueCodes(issues) != "advisory:puda_consumer_limit_near:COMMAND_QUEUE" {
		t.Fatalf("status=%s issues=%s", report.Status, issueCodes(issues))
	}
	report.Servers[0].Version = "2.12.2"
	if issues := BuildIssues(report); len(issues) != 0 {
		t.Fatalf("pre-2.15 servers have no default limit, issues=%s", issueCodes(issues))
	}
	streams["COMMAND_QUEUE"].Config.MaxConsumers = 5000
	report = applyPUDAHealth(okReport(""), checkPUDAResources(streams))
	if issues := BuildIssues(report); len(issues) != 0 {
		t.Fatalf("explicit stream limit, issues=%s", issueCodes(issues))
	}
}

func TestEndpointIssuesSeverityAndSource(t *testing.T) {
	report := summarizeHealth([]ServerHealth{
		{URL: "nats://n1:4222", Status: "ok", ID: "N1", Cluster: "puda"},
		{URL: "nats://10.0.0.3:4222", Status: "error", Error: "nats: no servers available for connection"},
		{URL: "tls://n4:4443", Status: "error", Error: "tls: failed to verify certificate: x509: unknown authority"},
	}, JetStreamHealth{Status: "ok", OK: true})
	issues := BuildIssues(report)
	if got := issueCodes(issues); got != "degraded:endpoint_unreachable:nats://10.0.0.3:4222,degraded:endpoint_tls_error:tls://n4:4443" {
		t.Fatalf("issues=%s", got)
	}
	if issues[0].Source != "servers[1].error" || !strings.Contains(issues[0].NextStep, "ip route get 10.0.0.3") || !strings.Contains(issues[0].NextStep, "grep 4222") {
		t.Fatalf("issue=%+v", issues[0])
	}

	down := summarizeHealth([]ServerHealth{{URL: "nats://n1:4222", Status: "error", Error: "refused"}}, JetStreamHealth{Status: "not_checked", Reason: "nats_unreachable"})
	if got := issueCodes(BuildIssues(down)); got != "unhealthy:endpoint_unreachable:nats://n1:4222" {
		t.Fatalf("all endpoints down issues=%s", got)
	}
}

func TestEveryNonOKStatusHasMatchingIssue(t *testing.T) {
	reports := []HealthReport{
		summarizeHealth([]ServerHealth{{URL: "nats://a:4222", Status: "ok", ID: "A", Cluster: "east"}, {URL: "nats://b:4222", Status: "ok", ID: "B", Cluster: "west"}}, JetStreamHealth{Status: "ok", OK: true}),
		summarizeHealth([]ServerHealth{{URL: "nats://a:4222", Status: "ok", ID: "A"}}, JetStreamHealth{Status: "failed", Reason: "jetstream_no_quorum", Error: "JetStream system temporarily unavailable"}),
	}
	for _, report := range reports {
		issues := BuildIssues(report)
		found := false
		for _, issue := range issues {
			found = found || issue.Severity == report.Status
		}
		if report.Status == HealthOK || !found {
			t.Fatalf("status=%s issues=%s", report.Status, issueCodes(issues))
		}
	}
	if issues := BuildIssues(reports[1]); issues[0].Code != "jetstream_no_quorum" || !strings.Contains(issues[0].NextStep, "Start the stopped NATS nodes") {
		t.Fatalf("issues=%+v", issues)
	}
}

func TestGatewayIssuesNeverUnhealthy(t *testing.T) {
	report := okReport("puda")
	report.Gateways = summarizeGateways([]probe{
		{server: ServerHealth{URL: "nats://remote:4222", Status: "error", Error: "timeout"}, js: JetStreamHealth{Status: "not_checked"}},
	})
	issues := BuildIssues(report)
	if got := issueCodes(issues); got != "degraded:gateway_endpoint_unreachable:nats://remote:4222" || issues[0].Source != "gateways[0].servers[0].error" {
		t.Fatalf("issues=%s %+v", got, issues)
	}
}

func TestJetStreamNoQuorumMessages(t *testing.T) {
	for _, message := range []string{"nats: JetStream system temporarily unavailable", "no metadata leader"} {
		if !jetStreamNoQuorum(message) {
			t.Fatalf("%q not recognised", message)
		}
	}
	if jetStreamNoQuorum("nats: jetstream not enabled for account") {
		t.Fatal("disabled JetStream is not a quorum loss")
	}
}

func TestGroupBrokersKeepsEndpointsPerID(t *testing.T) {
	brokers, unidentified := groupBrokers([]ServerHealth{
		{URL: "nats://lan:4222", Status: "ok", ID: "NSAME", Name: "nats1"},
		{URL: "nats://other:4222", Status: "ok", ID: "NOTHER", Name: "nats1"},
		{URL: "nats://ts:4222", Status: "ok", ID: "NSAME", Name: "nats1"},
		{URL: "nats://down:4222", Status: "error", ID: "NSAME"},
		{URL: "nats://noid:4222", Status: "ok"},
	})
	if unidentified != 1 || len(brokers) != 2 {
		t.Fatalf("brokers=%+v unidentified=%d", brokers, unidentified)
	}
	if brokers[0].ID != "NSAME" || strings.Join(brokers[0].Endpoints, ",") != "nats://lan:4222,nats://ts:4222" || brokers[1].ID != "NOTHER" {
		t.Fatalf("brokers=%+v", brokers)
	}
}

func TestPUDAResourceMinorityReplicasIsNoQuorum(t *testing.T) {
	// Right after two of three nodes stop, the old leader still claims leadership.
	streams := allStreams(3, &natsio.ClusterInfo{Leader: "nats1", Replicas: []*natsio.PeerInfo{{Name: "nats2", Offline: true}, {Name: "nats3", Offline: true}}})
	report := applyPUDAHealth(okReport("puda"), checkPUDAResources(streams))
	issues := BuildIssues(report)
	if report.Status != HealthUnhealthy || len(issues) != 1 || issues[0].Code != "puda_resource_no_quorum" || strings.Count(issues[0].Target, ",") != 4 || !strings.Contains(issues[0].Detail, "nats2, nats3") {
		t.Fatalf("status=%s issues=%+v", report.Status, issues)
	}
}
