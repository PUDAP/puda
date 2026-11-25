package nats

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	natsio "github.com/nats-io/nats.go"
)

const (
	HealthOK        = "ok"
	HealthDegraded  = "degraded"
	HealthUnhealthy = "unhealthy"
)

// ServerHealth is the probe result for one configured NATS URL.
type ServerHealth struct {
	URL               string   `json:"url"`
	Status            string   `json:"status"`
	Name              string   `json:"name,omitempty"`
	ID                string   `json:"id,omitempty"`
	Version           string   `json:"version,omitempty"`
	Cluster           string   `json:"cluster,omitempty"`
	JetStream         bool     `json:"jetstream"`
	RTTMS             float64  `json:"rtt_ms,omitempty"`
	DiscoveredServers []string `json:"discovered_servers,omitempty"`
	Error             string   `json:"error,omitempty"`
}

// ClusterHealth summarizes the configured endpoints. Configured, Reachable and
// Discovered count endpoint URLs, not brokers: one broker reachable through two
// addresses (e.g. LAN and Tailscale) is two endpoints. Brokers counts distinct
// server IDs among reachable endpoints; endpoints that reported no ID are
// counted in UnidentifiedEndpoints instead of being grouped by name.
type ClusterHealth struct {
	Name       string   `json:"name,omitempty"`
	Configured int      `json:"configured"`
	Reachable  int      `json:"reachable"`
	Discovered []string `json:"discovered"`
	// Brokers lists each distinct non-empty server ID that responded, with the
	// configured endpoints that reached it, in configuration order.
	Brokers []BrokerHealth `json:"brokers"`
	// UnidentifiedEndpoints responded without a server ID and are not in Brokers.
	UnidentifiedEndpoints int `json:"unidentified_endpoints,omitempty"`
}

// BrokerHealth is one broker (one server ID) and the endpoints that reached it.
type BrokerHealth struct {
	ID        string   `json:"id"`
	Name      string   `json:"name,omitempty"`
	Endpoints []string `json:"endpoints"`
}

// JetStreamHealth is the account-level JetStream probe from a reachable node.
type JetStreamHealth struct {
	Status    string `json:"status"`
	Reason    string `json:"reason,omitempty"`
	OK        bool   `json:"ok"`
	Streams   int    `json:"streams,omitempty"`
	Consumers int    `json:"consumers,omitempty"`
	Memory    uint64 `json:"memory,omitempty"`
	Storage   uint64 `json:"storage,omitempty"`
	Error     string `json:"error,omitempty"`
}

// GatewayHealth is one expected remote cluster reached through a NATS gateway.
type GatewayHealth struct {
	Cluster    string `json:"cluster,omitempty"`
	Status     string `json:"status"`
	Configured int    `json:"configured"`
	Reachable  int    `json:"reachable"`
	// Brokers and UnidentifiedEndpoints follow ClusterHealth's definitions.
	Brokers               []BrokerHealth  `json:"brokers"`
	UnidentifiedEndpoints int             `json:"unidentified_endpoints,omitempty"`
	Servers               []ServerHealth  `json:"servers"`
	JetStream             JetStreamHealth `json:"jetstream"`
}

// CompatibilityHealth is advisory and never determines NATS health.
type CompatibilityHealth struct {
	Status            string                       `json:"status"`
	Reason            string                       `json:"reason,omitempty"`
	Error             string                       `json:"error,omitempty"`
	AdvisoryOnly      bool                         `json:"advisory_only"`
	SupportedProtocol string                       `json:"supported_protocol"`
	Machines          []MachineCompatibilityHealth `json:"machines"`
}

// MachineCompatibilityHealth judges one unique live pong's protocol_version,
// not stored inventory. Status is ProtocolSupported or ProtocolUnsupported.
type MachineCompatibilityHealth struct {
	MachineID       string `json:"machine_id"`
	SDKVersion      string `json:"sdk_version"`
	ProtocolVersion string `json:"protocol_version"`
	Status          string `json:"status"`
}

// HealthReport is the full NATS server/cluster healthcheck result.
type HealthReport struct {
	Status string `json:"status"`
	// Issues explains every non-ok status (and advisories) with a next step;
	// read status and issues first.
	Issues    []HealthIssue   `json:"issues"`
	Servers   []ServerHealth  `json:"servers"`
	Cluster   ClusterHealth   `json:"cluster"`
	JetStream JetStreamHealth `json:"jetstream"`
	// PUDA reports the local cluster's PUDA streams and KV buckets.
	PUDA     PUDAHealth      `json:"puda"`
	Gateways []GatewayHealth `json:"gateways"`
	// Advisory only; listed after the NATS checks that determine Status.
	Compatibility *CompatibilityHealth `json:"compatibility,omitempty"`
}

// WaitClosed waits for a connection's closed callback, bounded by limit so a
// missing callback cannot hang the caller. It reports whether closed fired.
func WaitClosed(closed <-chan struct{}, limit time.Duration) bool {
	timer := time.NewTimer(limit)
	defer timer.Stop()
	select {
	case <-closed:
		return true
	case <-timer.C:
		return false
	}
}

// SplitServerURLs splits a comma-separated NATS URL list, trimming blanks.
func SplitServerURLs(servers string) []string {
	parts := strings.Split(servers, ",")
	urls := make([]string, 0, len(parts))
	seen := make(map[string]struct{}, len(parts))
	for _, part := range parts {
		url := strings.TrimSpace(part)
		if url == "" {
			continue
		}
		if _, exists := seen[url]; exists {
			continue
		}
		seen[url] = struct{}{}
		urls = append(urls, url)
	}
	return urls
}

type probe struct {
	server ServerHealth
	js     JetStreamHealth
	puda   PUDAHealth
}

// CheckHealth probes each configured NATS URL independently and summarizes
// local cluster membership plus JetStream account access. gatewayServers are
// optional client URLs in remote clusters expected to be reachable through a
// NATS gateway; they are reported separately and do not join local membership.
func CheckHealth(servers, gatewayServers string, timeout time.Duration) (HealthReport, error) {
	urls := SplitServerURLs(servers)
	if len(urls) == 0 {
		return HealthReport{}, fmt.Errorf("no NATS server URLs provided")
	}
	if timeout <= 0 {
		timeout = 2 * time.Second
	}

	local := probeURLs(urls, timeout, true)
	report := summarizeHealth(collectServers(local), firstJetStream(local))
	report = applyPUDAHealth(report, firstPUDA(local))
	report.Gateways = summarizeGateways(probeURLs(SplitServerURLs(gatewayServers), timeout, false))
	return applyGatewayStatus(report), nil
}

func probeURLs(urls []string, timeout time.Duration, withPUDA bool) []probe {
	results := make([]probe, len(urls))
	var wg sync.WaitGroup
	for i, url := range urls {
		wg.Add(1)
		go func(i int, url string) {
			defer wg.Done()
			server, js, puda := probeServer(url, timeout, withPUDA)
			results[i] = probe{server: server, js: js, puda: puda}
		}(i, url)
	}
	wg.Wait()
	return results
}

func collectServers(results []probe) []ServerHealth {
	servers := make([]ServerHealth, len(results))
	for i, result := range results {
		servers[i] = result.server
	}
	return servers
}

func firstJetStream(results []probe) JetStreamHealth {
	js := JetStreamHealth{Status: "not_checked", Reason: "nats_unreachable"}
	for _, result := range results {
		if result.server.Status != "ok" {
			continue
		}
		if !js.OK {
			js = result.js
		}
	}
	return js
}

// firstPUDA returns the PUDA resource check from the same endpoint whose
// JetStream result is reported.
func firstPUDA(results []probe) PUDAHealth {
	for _, result := range results {
		if result.server.Status == "ok" && result.js.OK {
			return result.puda
		}
	}
	return PUDAHealth{Status: "not_checked", Reason: "jetstream_unavailable", Resources: []PUDAResource{}}
}

// ProbeServer connects to a single NATS URL without failing over to other nodes.
func ProbeServer(serverURL string, timeout time.Duration) (ServerHealth, JetStreamHealth) {
	server, js, _ := probeServer(serverURL, timeout, false)
	return server, js
}

func probeServer(serverURL string, timeout time.Duration, withPUDA bool) (ServerHealth, JetStreamHealth, PUDAHealth) {
	puda := PUDAHealth{Status: "not_checked", Reason: "jetstream_unavailable", Resources: []PUDAResource{}}
	health := ServerHealth{URL: serverURL, Status: "error"}
	// Only this probe connection owns these handlers. Keep the first async
	// error (e.g. a JetStream API/reply permission violation) for the report
	// instead of nats.go's default unstructured stderr output.
	asyncErrors := make(chan error, 1)
	closed := make(chan struct{})
	opts, err := OptionsForServers(serverURL,
		natsio.Name("puda-healthcheck"),
		natsio.Timeout(timeout),
		natsio.MaxReconnects(0),
		natsio.DontRandomize(),
		natsio.ErrorHandler(func(_ *natsio.Conn, _ *natsio.Subscription, err error) {
			select {
			case asyncErrors <- err:
			default:
			}
		}),
		natsio.ClosedHandler(func(_ *natsio.Conn) { close(closed) }),
	)
	if err != nil {
		health.Error = err.Error()
		return health, JetStreamHealth{Status: "not_checked", Reason: "nats_unreachable"}, puda
	}
	nc, err := natsio.Connect(serverURL, opts...)
	if err != nil {
		health.Error = err.Error()
		return health, JetStreamHealth{Status: "not_checked", Reason: "nats_unreachable"}, puda
	}
	// Flush does not wait for async handlers: Close, then await the FIFO
	// closed callback so no handler runs after the probe returns.
	closeAndWait := func() {
		nc.Close()
		WaitClosed(closed, timeout)
	}

	start := time.Now()
	if err := nc.FlushTimeout(timeout); err != nil {
		closeAndWait()
		health.Error = err.Error()
		return health, JetStreamHealth{Status: "not_checked", Reason: "nats_unreachable"}, puda
	}
	health.RTTMS = float64(time.Since(start).Microseconds()) / 1000.0
	health.Status = "ok"
	health.Name = nc.ConnectedServerName()
	health.ID = nc.ConnectedServerId()
	health.Version = nc.ConnectedServerVersion()
	health.Cluster = nc.ConnectedClusterName()
	jsEnabled, _ := nc.ConnectedServerJetStream()
	health.JetStream = jsEnabled
	health.DiscoveredServers = uniqueSorted(nc.DiscoveredServers())
	js := jetStreamFromConn(nc, timeout)
	if js.OK && withPUDA {
		puda = pudaFromConn(nc, timeout)
	}
	closeAndWait()
	// A denied $JS.API publish or reply subscription surfaces only as a
	// request timeout; report the captured server cause instead.
	if !js.OK {
		select {
		case asyncErr := <-asyncErrors:
			js.Error = asyncErr.Error()
		default:
		}
	}
	return health, js, puda
}

func jetStreamFromConn(nc *natsio.Conn, timeout time.Duration) JetStreamHealth {
	js, err := nc.JetStream(natsio.MaxWait(timeout))
	if err != nil {
		return JetStreamHealth{Status: "failed", Reason: "jetstream_error", Error: err.Error()}
	}
	info, err := js.AccountInfo()
	if err != nil {
		reason := "jetstream_error"
		if jetStreamNoQuorum(err.Error()) {
			reason = "jetstream_no_quorum"
		}
		return JetStreamHealth{Status: "failed", Reason: reason, Error: err.Error()}
	}
	return JetStreamHealth{
		Status:    "ok",
		OK:        true,
		Streams:   info.Streams,
		Consumers: info.Consumers,
		Memory:    info.Memory,
		Storage:   info.Store,
	}
}

// groupBrokers groups reachable endpoints by non-empty server ID. Names and URLs
// never identify a broker: two servers may share a name, and one server may be
// reachable at several URLs. Endpoints without an ID are only counted.
func groupBrokers(servers []ServerHealth) (brokers []BrokerHealth, unidentified int) {
	brokers = []BrokerHealth{}
	index := make(map[string]int)
	for _, server := range servers {
		if server.Status != "ok" {
			continue
		}
		id := strings.TrimSpace(server.ID)
		if id == "" {
			unidentified++
			continue
		}
		i, seen := index[id]
		if !seen {
			i = len(brokers)
			index[id] = i
			brokers = append(brokers, BrokerHealth{ID: id, Name: server.Name, Endpoints: []string{}})
		}
		brokers[i].Endpoints = append(brokers[i].Endpoints, server.URL)
	}
	return brokers, unidentified
}

// applyPUDAHealth attaches the PUDA resource check and lets it lower status:
// a missing or leaderless required resource makes PUDA unusable (unhealthy);
// an under-replicated or lagging one is degraded.
func applyPUDAHealth(report HealthReport, puda PUDAHealth) HealthReport {
	report.PUDA = finishPUDAHealth(puda, report.Cluster.Name != "")
	if report.PUDA.Resources == nil {
		report.PUDA.Resources = []PUDAResource{}
	}
	switch {
	case report.Status == HealthUnhealthy:
	case report.PUDA.Status == "failed":
		report.Status = HealthUnhealthy
	case report.PUDA.Status == "degraded":
		report.Status = HealthDegraded
	}
	return report
}

func summarizeHealth(servers []ServerHealth, js JetStreamHealth) HealthReport {
	reachable := 0
	discovered := make([]string, 0)
	clusterNames := make(map[string]struct{})
	for _, server := range servers {
		if server.Status == "ok" {
			reachable++
			if server.Cluster != "" {
				clusterNames[server.Cluster] = struct{}{}
			}
			discovered = append(discovered, server.URL)
			discovered = append(discovered, server.DiscoveredServers...)
		}
	}

	clusterName := uniqueJoin(clusterNames)
	brokers, unidentified := groupBrokers(servers)
	report := HealthReport{
		Servers:   servers,
		JetStream: js,
		Gateways:  []GatewayHealth{},
		Cluster: ClusterHealth{
			Name:       clusterName,
			Configured: len(servers),
			Reachable:  reachable,
			Discovered: uniqueSorted(discovered),

			Brokers:               brokers,
			UnidentifiedEndpoints: unidentified,
		},
	}

	switch {
	case reachable == 0:
		report.Status = HealthUnhealthy
	case !js.OK:
		report.Status = HealthUnhealthy
	case reachable < len(servers) || len(clusterNames) > 1:
		report.Status = HealthDegraded
	default:
		report.Status = HealthOK
	}
	return report
}

func summarizeGateways(results []probe) []GatewayHealth {
	if len(results) == 0 {
		return []GatewayHealth{}
	}

	type group struct {
		probes []probe
	}
	groups := make(map[string]*group)
	order := make([]string, 0)
	var unknown []probe
	for _, result := range results {
		if result.server.Status == "ok" {
			name := result.server.Cluster
			if _, exists := groups[name]; !exists {
				groups[name] = &group{}
				order = append(order, name)
			}
			groups[name].probes = append(groups[name].probes, result)
			continue
		}
		unknown = append(unknown, result)
	}

	if len(unknown) > 0 {
		if len(order) == 1 {
			groups[order[0]].probes = append(groups[order[0]].probes, unknown...)
		} else {
			name := ""
			if _, exists := groups[name]; !exists {
				groups[name] = &group{}
				order = append(order, name)
			}
			groups[name].probes = append(groups[name].probes, unknown...)
		}
	}

	gateways := make([]GatewayHealth, 0, len(order))
	for _, name := range order {
		probes := groups[name].probes
		servers := collectServers(probes)
		reachable := 0
		for _, server := range servers {
			if server.Status == "ok" {
				reachable++
			}
		}
		js := firstJetStream(probes)
		brokers, unidentified := groupBrokers(servers)
		gateway := GatewayHealth{
			Cluster:               name,
			Configured:            len(servers),
			Reachable:             reachable,
			Brokers:               brokers,
			UnidentifiedEndpoints: unidentified,
			Servers:               servers,
			JetStream:             js,
		}
		switch {
		case reachable == 0:
			gateway.Status = HealthUnhealthy
		case !js.OK || reachable < len(servers):
			gateway.Status = HealthDegraded
		default:
			gateway.Status = HealthOK
		}
		gateways = append(gateways, gateway)
	}
	return gateways
}

func applyGatewayStatus(report HealthReport) HealthReport {
	if report.Gateways == nil {
		report.Gateways = []GatewayHealth{}
	}
	if report.Status == HealthUnhealthy {
		return report
	}
	for _, gateway := range report.Gateways {
		if gateway.Status != HealthOK {
			report.Status = HealthDegraded
			return report
		}
	}
	return report
}

func uniqueSorted(values []string) []string {
	if len(values) == 0 {
		return []string{}
	}
	seen := make(map[string]struct{}, len(values))
	out := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		if _, exists := seen[value]; exists {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	sort.Strings(out)
	return out
}

func uniqueJoin(values map[string]struct{}) string {
	if len(values) == 0 {
		return ""
	}
	names := make([]string, 0, len(values))
	for name := range values {
		names = append(names, name)
	}
	sort.Strings(names)
	return strings.Join(names, ",")
}
