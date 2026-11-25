package cli

import (
	"fmt"
	"io"
	"strings"
	"time"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

var healthcheckHuman bool
var healthcheckTimeout time.Duration

var healthcheckCmd = &cobra.Command{
	Use:   "healthcheck",
	Short: "Check NATS server and cluster health",
	Long: `Probe each configured NATS URL independently and report server, cluster, and JetStream health.

A down cluster node is reported even when another node still accepts connections.
A successful check also verifies JetStream account access.

Agents: read status and issues first. Every degraded or unhealthy status has
at least one issue of that severity; each issue has a code, target, the JSON
path holding its evidence (source) and a next_step. Advisory issues never
change status. One cause affecting several resources is one issue.

PUDA resources: the local cluster must have the PUDA streams (COMMAND_QUEUE,
RESPONSE_QUEUE, RESPONSE_IMMEDIATE) and KV buckets (MACHINE_STATE,
MACHINE_COMMANDS). Missing, leaderless or below-quorum ones make the report
unhealthy; one replica in a cluster, or a lagging replica, is degraded.
LIVESTREAMS and E2E_* are created on demand and only advisory.

Each configured URL is an endpoint. One broker reachable through several
addresses (for example LAN and Tailscale) is several endpoints but one broker.
cluster.configured, cluster.reachable and cluster.discovered count endpoint URLs;
cluster.brokers lists each distinct server ID that responded with its endpoints.
Endpoints that report no server ID are counted in
cluster.unidentified_endpoints, never grouped by name.
Advertised addresses alone do not prove broker identity or cluster membership.
A standalone server (no cluster name) is not shown as a cluster in --human output.

The active profile's gateway_servers are client URLs in a
remote cluster expected through a NATS gateway. Those remotes are probed and
reported separately; a different cluster name is expected and is not degraded.
JetStream is reported per cluster, not blended.

A fresh fleet ping checks the protocol_version every responding edge reports in
its pong. compatibility.supported_protocol is the Edge Protocol this CLI speaks
(1.x); each compatibility.machines entry is "supported" for a 1.x edge and
"unsupported" otherwise, including edges that report no protocol_version (they
predate Edge Protocol 1.0, i.e. Python SDK before 0.1.0). For an unsupported
edge, update the PUDA SDK on that machine. The advisory-only compatibility result
is included in the report and never changes NATS health or exit status. No replies
or failed discovery means compatibility was not checked; offline edges cannot be evaluated.
Transport errors appear once per affected server; dependent checks use status/reason.
A completed report does not print compatibility prose or redundant errors to stderr.

Output is a JSON object by default. Use --human for a text summary.
The command exits non-zero if the local cluster is degraded or unhealthy, or if
an expected gateway remote is not fully healthy.`,
	Args: cobra.NoArgs,
	RunE: runHealthcheck,
}

func init() {
	healthcheckCmd.Flags().BoolVar(&healthcheckHuman, "human", false, "Output as human-readable text instead of JSON")
	healthcheckCmd.Flags().DurationVar(&healthcheckTimeout, "timeout", 2*time.Second, "Timeout for each server probe and the fleet pong collection window")
}

// Only returned after a complete report was successfully written. Execute keeps
// the failure exit code without printing a redundant unstructured error.
type healthcheckReportedError struct{ status string }

func (e *healthcheckReportedError) Error() string { return "NATS healthcheck " + e.status }

func runHealthcheck(cmd *cobra.Command, args []string) error {
	conn, err := prepareConnection()
	if err != nil {
		return err
	}
	servers := conn.Servers
	gateways := conn.GatewayServers

	report, err := pudanats.CheckHealth(servers, gateways, healthcheckTimeout)
	if err != nil {
		return err
	}
	report.Compatibility = checkHealthCompatibility(report, healthcheckTimeout)
	report.Issues = pudanats.BuildIssues(report)
	if err := writeHealthReport(cmd.OutOrStdout(), report, healthcheckHuman); err != nil {
		return err
	}
	if report.Status != pudanats.HealthOK {
		return &healthcheckReportedError{status: report.Status}
	}
	return nil
}

// Discovery is bounded and advisory. Probe failures live only on their servers;
// connect only to successfully probed local URLs, never re-diagnose known failures.
func checkHealthCompatibility(report pudanats.HealthReport, timeout time.Duration) *pudanats.CompatibilityHealth {
	result := &pudanats.CompatibilityHealth{
		Status: "not_checked", Reason: "nats_unreachable", AdvisoryOnly: true,
		SupportedProtocol: pudanats.SupportedProtocol, Machines: []pudanats.MachineCompatibilityHealth{},
	}
	if report.Cluster.Reachable == 0 {
		return result
	}
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	var urls []string
	for _, server := range report.Servers {
		if server.Status == "ok" {
			urls = append(urls, server.URL)
		}
	}
	result.Reason = "discovery_error"
	// Only this advisory connection owns these handlers. Keep the first async
	// discovery error instead of nats.go's default unstructured stderr output.
	discoveryErrors := make(chan error, 1)
	closed := make(chan struct{})
	nc, err := pudanats.Connect(strings.Join(urls, ","), natsio.Timeout(timeout), natsio.NoReconnect(),
		natsio.ErrorHandler(func(_ *natsio.Conn, _ *natsio.Subscription, err error) {
			select {
			case discoveryErrors <- err:
			default:
			}
		}),
		natsio.ClosedHandler(func(_ *natsio.Conn) { close(closed) }),
	)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	pongs, err := pudanats.ListMachinePongs(nc, timeout)
	// ListMachinePongs flushes both the SUB and PUB, so server permission
	// errors are parsed before it finishes. Flush does not wait for async
	// handlers: Close then await the FIFO closed callback before reading the
	// captured error, including when discovery returned early or timed out.
	nc.Close()
	pudanats.WaitClosed(closed, timeout)
	select {
	case discoveryErr := <-discoveryErrors:
		if err == nil {
			err = discoveryErr
		}
	default:
	}
	return evaluateHealthCompatibility(pongs, err)
}

// evaluateHealthCompatibility keeps edges that replied even when discovery
// also reported an error; reason discovery_incomplete marks a partial result.
func evaluateHealthCompatibility(pongs []pudanats.PingResult, discoveryErr error) *pudanats.CompatibilityHealth {
	result := &pudanats.CompatibilityHealth{
		Status: "not_checked", AdvisoryOnly: true,
		SupportedProtocol: pudanats.SupportedProtocol, Machines: []pudanats.MachineCompatibilityHealth{},
	}
	if discoveryErr != nil {
		result.Error = discoveryErr.Error()
	}
	if len(pongs) == 0 {
		result.Reason = "no_responders"
		if discoveryErr != nil {
			result.Reason = "discovery_error"
		}
		return result
	}
	result.Status = pudanats.ProtocolSupported
	if discoveryErr != nil {
		result.Reason = "discovery_incomplete"
	}
	// ListMachinePongs already validates and deduplicates successful responders.
	for _, pong := range pongs {
		status := pudanats.ClassifyProtocol(pong.ProtocolVersion)
		result.Machines = append(result.Machines, pudanats.MachineCompatibilityHealth{
			MachineID: pong.MachineID, SDKVersion: pong.SDKVersion,
			ProtocolVersion: pong.ProtocolVersion, Status: status,
		})
		if status == pudanats.ProtocolUnsupported {
			result.Status = pudanats.ProtocolUnsupported
		}
	}
	return result
}

func writeHealthReport(w io.Writer, report pudanats.HealthReport, human bool) error {
	if report.Servers == nil {
		report.Servers = []pudanats.ServerHealth{}
	}
	if report.Cluster.Discovered == nil {
		report.Cluster.Discovered = []string{}
	}
	if report.Gateways == nil {
		report.Gateways = []pudanats.GatewayHealth{}
	}
	if report.Issues == nil {
		report.Issues = []pudanats.HealthIssue{}
	}
	if report.Cluster.Brokers == nil {
		report.Cluster.Brokers = []pudanats.BrokerHealth{}
	}
	if report.PUDA.Resources == nil {
		report.PUDA.Resources = []pudanats.PUDAResource{}
	}
	if !human {
		return writeJSON(w, report)
	}

	destination := w
	var text strings.Builder
	w = &text
	fmt.Fprintf(w, "status: %s\n", report.Status)
	if len(report.Issues) > 0 {
		fmt.Fprintln(w, "issues:")
		for _, issue := range report.Issues {
			target := ""
			if issue.Target != "" {
				target = " " + issue.Target
			}
			detail := ""
			if issue.Detail != "" {
				detail = ": " + issue.Detail
			}
			if issue.Source != "" {
				detail += " (see " + issue.Source + ")"
			}
			fmt.Fprintf(w, "  [%s] %s%s%s\n    next: %s\n", issue.Severity, issue.Code, target, detail, issue.NextStep)
		}
	}
	fmt.Fprintf(w, "endpoints: %d/%d reachable\n", report.Cluster.Reachable, report.Cluster.Configured)
	writeHumanEndpoints(w, "  ", report.Servers)
	fmt.Fprintf(w, "unique brokers responding: %d%s\n", len(report.Cluster.Brokers), unidentifiedNote(report.Cluster.UnidentifiedEndpoints))
	// A standalone server has no cluster name; it is not a cluster. Advertised
	// addresses (cluster.discovered, JSON only) prove neither identity nor size.
	if report.Cluster.Name != "" {
		fmt.Fprintf(w, "cluster: %s\n", report.Cluster.Name)
	}
	if report.JetStream.OK {
		fmt.Fprintf(
			w,
			"jetstream: ok streams=%d consumers=%d memory=%d storage=%d\n",
			report.JetStream.Streams,
			report.JetStream.Consumers,
			report.JetStream.Memory,
			report.JetStream.Storage,
		)
	} else if report.JetStream.Status == "not_checked" {
		fmt.Fprintf(w, "jetstream: not_checked: %s\n", report.JetStream.Reason)
	} else {
		fmt.Fprintf(w, "jetstream: failed: %s\n", report.JetStream.Error)
	}
	writeHumanPUDA(w, report.PUDA)
	if result := report.Compatibility; result != nil {
		fmt.Fprintf(w, "compatibility: %s (advisory only) supported_protocol=%s", result.Status, result.SupportedProtocol)
		if result.Reason != "" {
			fmt.Fprintf(w, " reason=%s", result.Reason)
		}
		if result.Error != "" {
			fmt.Fprintf(w, " error=%s", result.Error)
		}
		fmt.Fprintln(w)
		for _, edge := range result.Machines {
			fmt.Fprintf(w, "  %s: protocol=%s sdk=%q %s\n", edge.MachineID, pudanats.ProtocolLabel(edge.ProtocolVersion), edge.SDKVersion, edge.Status)
		}
	}
	if len(report.Gateways) == 0 {
		_, err := io.WriteString(destination, text.String())
		return err
	}
	fmt.Fprintf(w, "gateways: %d\n", len(report.Gateways))
	for _, gateway := range report.Gateways {
		clusterLabel := gateway.Cluster
		if clusterLabel == "" {
			clusterLabel = "(none)"
		}
		fmt.Fprintf(w, "  %s: %s endpoints=%d/%d reachable unique brokers=%d%s\n", clusterLabel, gateway.Status, gateway.Reachable, gateway.Configured, len(gateway.Brokers), unidentifiedNote(gateway.UnidentifiedEndpoints))
		writeHumanEndpoints(w, "    ", gateway.Servers)
		if gateway.JetStream.OK {
			fmt.Fprintf(
				w,
				"    jetstream: ok streams=%d consumers=%d memory=%d storage=%d\n",
				gateway.JetStream.Streams,
				gateway.JetStream.Consumers,
				gateway.JetStream.Memory,
				gateway.JetStream.Storage,
			)
		} else if gateway.JetStream.Status == "not_checked" {
			fmt.Fprintf(w, "    jetstream: not_checked: %s\n", gateway.JetStream.Reason)
		} else {
			fmt.Fprintf(w, "    jetstream: failed: %s\n", gateway.JetStream.Error)
		}
	}
	_, err := io.WriteString(destination, text.String())
	return err
}

// writeHumanEndpoints prints one line per configured endpoint URL, including the
// server ID that identifies the broker behind it.
func writeHumanEndpoints(w io.Writer, indent string, servers []pudanats.ServerHealth) {
	for _, server := range servers {
		if server.Status != "ok" {
			fmt.Fprintf(w, "%s%s: failed: %s\n", indent, server.URL, server.Error)
			continue
		}
		id := server.ID
		if id == "" {
			id = "(none)"
		}
		cluster := ""
		if server.Cluster != "" {
			cluster = " cluster=" + server.Cluster
		}
		fmt.Fprintf(
			w,
			"%s%s: ok %.3fms name=%s id=%s%s js=%t version=%s\n",
			indent,
			server.URL,
			server.RTTMS,
			server.Name,
			id,
			cluster,
			server.JetStream,
			server.Version,
		)
	}
}

func unidentifiedNote(count int) string {
	if count == 0 {
		return ""
	}
	return fmt.Sprintf(" (%d reachable endpoint(s) reported no server ID; not counted)", count)
}

// writeHumanPUDA prints one line for the PUDA streams and KV buckets, naming
// only the resources that are not ok.
func writeHumanPUDA(w io.Writer, puda pudanats.PUDAHealth) {
	if puda.Status == "" {
		return
	}
	if puda.Status == "not_checked" {
		fmt.Fprintf(w, "puda resources: not_checked: %s\n", puda.Reason)
		return
	}
	required, ready := 0, 0
	var problems []string
	for _, resource := range puda.Resources {
		if resource.Required {
			required++
			if resource.Status == pudanats.ResourceOK {
				ready++
			}
		}
		if resource.Status != pudanats.ResourceOK && (resource.Required || resource.Status != pudanats.ResourceMissing) {
			problems = append(problems, resource.Name+"="+resource.Status)
		}
	}
	fmt.Fprintf(w, "puda resources: %s %d/%d required ok", puda.Status, ready, required)
	if len(problems) > 0 {
		fmt.Fprintf(w, " (%s)", strings.Join(problems, ", "))
	}
	fmt.Fprintln(w)
}
