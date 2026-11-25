package nats

import (
	"fmt"
	"net/url"
	"strings"
)

// Issue severities. HealthUnhealthy and HealthDegraded issues explain the
// report status; advisory issues never change it.
const IssueAdvisory = "advisory"

// HealthIssue is one finding an agent should act on, with a concrete next step.
// Error text is not copied: Source is the JSON path of the report field that
// holds the evidence (e.g. servers[1].error), so each error appears once.
type HealthIssue struct {
	Code     string `json:"code"`
	Severity string `json:"severity"`
	Target   string `json:"target,omitempty"`
	Detail   string `json:"detail,omitempty"`
	Source   string `json:"source,omitempty"`
	NextStep string `json:"next_step"`
}

// consumerLimitWarnAt is 90% of the NATS 2.15+ default per-stream consumer limit.
const consumerLimitWarnAt = 900

// BuildIssues derives the issue list from a finished report. Every non-ok
// status has at least one issue with that severity.
func BuildIssues(report HealthReport) []HealthIssue {
	issues := []HealthIssue{}
	issues = append(issues, endpointIssues(report)...)
	issues = append(issues, clusterIssues(report)...)
	issues = append(issues, jetStreamIssues("local", "jetstream", report.JetStream, HealthUnhealthy)...)
	issues = append(issues, pudaIssues(report)...)
	for i, gateway := range report.Gateways {
		issues = append(issues, gatewayIssues(i, gateway)...)
	}
	issues = append(issues, compatibilityIssues(report.Compatibility)...)
	return issues
}

func endpointIssues(report HealthReport) []HealthIssue {
	severity := HealthDegraded
	if report.Cluster.Reachable == 0 {
		severity = HealthUnhealthy
	}
	return failedEndpointIssues(report.Servers, severity, "endpoint", "servers")
}

func failedEndpointIssues(servers []ServerHealth, severity, prefix, path string) []HealthIssue {
	issues := []HealthIssue{}
	for i, server := range servers {
		if server.Status == "ok" {
			continue
		}
		host, port := hostPort(server.URL)
		issue := HealthIssue{
			Code:     prefix + "_unreachable",
			Severity: severity,
			Target:   server.URL,
			Source:   fmt.Sprintf("%s[%d].error", path, i),
			NextStep: fmt.Sprintf("Check the route and the NATS listener: `ip route get %s` here, then on the broker host `docker compose ps` in its nats folder and `ss -ltnp | grep %s`.", host, port),
		}
		if tlsError(server.Error) {
			issue.Code = prefix + "_tls_error"
			issue.NextStep = fmt.Sprintf("Check the profile's CA file (`puda profile list`), tls:// vs nats:// in the URL, and that the server certificate covers %s.", host)
		}
		issues = append(issues, issue)
	}
	return issues
}

func clusterIssues(report HealthReport) []HealthIssue {
	if !strings.Contains(report.Cluster.Name, ",") {
		return nil
	}
	return []HealthIssue{{
		Code:     "cluster_name_mismatch",
		Severity: HealthDegraded,
		Target:   report.Cluster.Name,
		Detail:   "the configured endpoints reach different NATS clusters",
		NextStep: "Keep one cluster's URLs in the profile servers; put URLs of remote clusters reached through a gateway in gateway_servers.",
	}}
}

func jetStreamIssues(target, path string, js JetStreamHealth, severity string) []HealthIssue {
	if js.OK || js.Status == "not_checked" {
		return nil
	}
	issue := HealthIssue{
		Code:     "jetstream_unavailable",
		Severity: severity,
		Target:   target,
		Source:   path + ".error",
		NextStep: "Check that JetStream is enabled in nats.conf and that this account may use the JetStream API ($JS.API.>).",
	}
	if js.Reason == "jetstream_no_quorum" {
		issue.Code = "jetstream_no_quorum"
		issue.NextStep = "Too few cluster nodes are running for JetStream quorum. Start the stopped NATS nodes; a three-node cluster needs two."
	}
	return []HealthIssue{issue}
}

func pudaIssues(report HealthReport) []HealthIssue {
	issues := []HealthIssue{}
	// One root cause (never provisioned, or created by an edge with one
	// replica) affects several resources; report it once with every target.
	var missing, underReplicated, missingSources, underSources []string
	for i, resource := range report.PUDA.Resources {
		source := fmt.Sprintf("puda.resources[%d]", i)
		severity := HealthUnhealthy
		if !resource.Required {
			severity = IssueAdvisory
		}
		switch resource.Status {
		case ResourceMissing:
			if resource.Required { // optional resources are created on demand
				missing = append(missing, resource.Name)
				missingSources = append(missingSources, source)
			}
		case ResourceUnderReplicated:
			if resource.Required {
				underReplicated = append(underReplicated, resource.Name)
				underSources = append(underSources, source)
			}
		case ResourceNoLeader:
			issues = append(issues, HealthIssue{
				Code: "puda_resource_no_leader", Severity: severity, Target: resource.Name, Source: source,
				Detail:   "no leader, so it cannot accept messages",
				NextStep: "Start the stopped NATS nodes. If all nodes are up, inspect with `nats stream report` (a leader election normally takes a few seconds).",
			})
		case ResourceNoQuorum:
			issues = append(issues, HealthIssue{
				Code: "puda_resource_no_quorum", Severity: severity, Target: resource.Name, Source: source,
				Detail:   fmt.Sprintf("only a minority of replicas is current (offline or behind: %s), so writes cannot commit", strings.Join(resource.LaggingReplicas, ", ")),
				NextStep: "Start the stopped NATS nodes; a three-replica stream needs two current replicas.",
			})
		case ResourceError:
			issues = append(issues, HealthIssue{
				Code: "puda_resource_unreadable", Severity: severity, Target: resource.Name, Source: source + ".error",
				NextStep: "Check that this account may read stream info ($JS.API.STREAM.INFO.>) and that JetStream is responsive.",
			})
		case ResourceReplicaLagging:
			if resource.Required {
				severity = HealthDegraded
			}
			issues = append(issues, HealthIssue{
				Code: "puda_resource_replica_lagging", Severity: severity, Target: resource.Name, Source: source,
				Detail:   fmt.Sprintf("replicas offline or behind: %s", strings.Join(resource.LaggingReplicas, ", ")),
				NextStep: "Normal for a few seconds after a node starts or replicas are added; re-run healthcheck. If it persists, check those NATS nodes are running and reachable from the leader on the cluster route port (6222).",
			})
		}
		if resource.Status != ResourceMissing && resource.MaxConsumers <= 0 && resource.Consumers >= consumerLimitWarnAt && serversAtLeast(report.Servers, 2, 15) {
			issues = append(issues, HealthIssue{
				Code: "puda_consumer_limit_near", Severity: IssueAdvisory, Target: resource.Name, Source: source,
				Detail:   fmt.Sprintf("%d consumers; NATS 2.15+ allows 1000 per stream by default", resource.Consumers),
				NextStep: "Unless nats.conf already raises it, set jetstream.limits.default_max_consumers: -1 (the infra/nats configs do) and restart the NATS servers.",
			})
		}
	}
	grouped := []HealthIssue{}
	if len(missing) > 0 {
		grouped = append(grouped, HealthIssue{
			Code: "puda_resources_missing", Severity: HealthUnhealthy, Target: strings.Join(missing, ","), Source: strings.Join(missingSources, ","),
			Detail:   "required PUDA streams/KV buckets do not exist; commands cannot be queued",
			NextStep: "Provision them once: " + setupStreamsStep(report),
		})
	}
	if len(underReplicated) > 0 {
		grouped = append(grouped, HealthIssue{
			Code: "puda_resources_under_replicated", Severity: HealthDegraded, Target: strings.Join(underReplicated, ","), Source: strings.Join(underSources, ","),
			Detail:   "1 replica in a cluster, so each is lost if its node goes down (usually an edge created them before provisioning)",
			NextStep: "Re-apply them with three replicas: " + setupStreamsStep(report),
		})
	}
	return append(grouped, mergeIssues(issues)...)
}

// mergeIssues folds issues that differ only in target into one issue, so a
// single cause (e.g. one node behind) is reported once with every resource.
func mergeIssues(issues []HealthIssue) []HealthIssue {
	merged := []HealthIssue{}
	index := map[string]int{}
	for _, issue := range issues {
		key := issue.Code + "\x00" + issue.Severity + "\x00" + issue.Detail + "\x00" + issue.NextStep
		if i, ok := index[key]; ok {
			merged[i].Target += "," + issue.Target
			merged[i].Source += "," + issue.Source
			continue
		}
		index[key] = len(merged)
		merged = append(merged, issue)
	}
	return merged
}

func gatewayIssues(index int, gateway GatewayHealth) []HealthIssue {
	name := gateway.Cluster
	if name == "" {
		name = "(unknown)"
	}
	issues := []HealthIssue{}
	severity := HealthDegraded // a gateway remote never makes the local cluster unhealthy
	path := fmt.Sprintf("gateways[%d]", index)
	issues = append(issues, failedEndpointIssues(gateway.Servers, severity, "gateway_endpoint", path+".servers")...)
	issues = append(issues, jetStreamIssues("gateway "+name, path+".jetstream", gateway.JetStream, severity)...)
	return issues
}

func compatibilityIssues(result *CompatibilityHealth) []HealthIssue {
	if result == nil {
		return nil
	}
	issues := []HealthIssue{}
	if result.Reason == "discovery_error" || result.Reason == "discovery_incomplete" {
		issues = append(issues, HealthIssue{
			Code: "compatibility_" + result.Reason, Severity: IssueAdvisory, Source: "compatibility.error",
			NextStep: "Check that this user may publish puda.cmd.ping and receive _INBOX replies.",
		})
	}
	for i, machine := range result.Machines {
		if machine.Status != "unsupported" {
			continue
		}
		issues = append(issues, HealthIssue{
			Code: "sdk_unsupported", Severity: IssueAdvisory, Target: machine.MachineID, Source: fmt.Sprintf("compatibility.machines[%d]", i),
			Detail:   fmt.Sprintf("edge protocol %s is not supported by this CLI (supports %s)", ProtocolLabel(machine.ProtocolVersion), SupportedProtocol),
			NextStep: fmt.Sprintf("Update the PUDA SDK on %s", machine.MachineID),
		})
	}
	return issues
}

func setupStreamsStep(report HealthReport) string {
	target := "nats://<nats-host>:4222"
	for _, server := range report.Servers {
		if server.Status == "ok" {
			target = server.URL
			break
		}
	}
	replicas := 1
	if report.Cluster.Name != "" {
		replicas = 3
	}
	return fmt.Sprintf("in services/nats/jetstream of the deployment monorepo (infra/nats/jetstream in the PUDA repo) run `NATS_URL=%s REPLICAS=%d ./setup_streams.sh`.", target, replicas)
}

func hostPort(raw string) (string, string) {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Host == "" {
		return raw, "4222"
	}
	port := parsed.Port()
	if port == "" {
		port = "4222"
	}
	return parsed.Hostname(), port
}

func tlsError(message string) bool {
	message = strings.ToLower(message)
	return strings.Contains(message, "tls") || strings.Contains(message, "x509") || strings.Contains(message, "certificate")
}

// serversAtLeast reports whether any reachable server runs at least major.minor.
func serversAtLeast(servers []ServerHealth, major, minor int) bool {
	for _, server := range servers {
		var gotMajor, gotMinor int
		if server.Status != "ok" {
			continue
		}
		if _, err := fmt.Sscanf(strings.TrimPrefix(server.Version, "v"), "%d.%d", &gotMajor, &gotMinor); err != nil {
			continue
		}
		if gotMajor > major || (gotMajor == major && gotMinor >= minor) {
			return true
		}
	}
	return false
}
