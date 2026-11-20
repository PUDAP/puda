package cli

import (
	"fmt"
	"io"
	"strings"
	"time"

	compatibility "github.com/PUDAP/puda"
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

Each configured URL is an endpoint. One broker reachable through several
addresses (for example LAN and Tailscale) is several endpoints but one broker.
cluster.configured, cluster.reachable and cluster.discovered count endpoint URLs;
cluster.brokers counts distinct server IDs that responded. Endpoints that report
no server ID are counted in cluster.unidentified_endpoints, never grouped by name.
Advertised addresses alone do not prove broker identity or cluster membership.
A standalone server (no cluster name) is not shown as a cluster in --human output.

The active profile's gateway_servers are client URLs in a
remote cluster expected through a NATS gateway. Those remotes are probed and
reported separately; a different cluster name is expected and is not degraded.
JetStream is reported per cluster, not blended.

A fresh fleet ping checks all responding edges' advertised Python SDK versions
against the bundled compatibility policy. The advisory-only compatibility result
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
		CLIVersion: Version, Machines: []pudanats.MachineCompatibilityHealth{},
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
		CLIVersion: Version, Machines: []pudanats.MachineCompatibilityHealth{},
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
	result.Status = "supported"
	if discoveryErr != nil {
		result.Reason = "discovery_incomplete"
	}
	policy := compatibility.Bundled()
	// ListMachinePongs already validates and deduplicates successful responders.
	for _, pong := range pongs {
		evaluation := policy.Evaluate(Version, pong.SDKVersion)
		ranges := evaluation.Ranges
		if ranges == nil {
			ranges = []compatibility.Range{}
		}
		result.Machines = append(result.Machines, pudanats.MachineCompatibilityHealth{
			MachineID: pong.MachineID, SDKVersion: pong.SDKVersion,
			Status: evaluation.Status, SupportedRanges: ranges,
		})
		if evaluation.Status == compatibility.Unsupported || (evaluation.Status == compatibility.Unknown && result.Status == "supported") {
			result.Status = string(evaluation.Status)
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
	if !human {
		return writeJSON(w, report)
	}

	destination := w
	var text strings.Builder
	w = &text
	fmt.Fprintf(w, "status: %s\n", report.Status)
	fmt.Fprintf(w, "endpoints: %d/%d reachable\n", report.Cluster.Reachable, report.Cluster.Configured)
	writeHumanEndpoints(w, "  ", report.Servers)
	fmt.Fprintf(w, "unique brokers responding: %d%s\n", report.Cluster.Brokers, unidentifiedNote(report.Cluster.UnidentifiedEndpoints))
	// A standalone server has no cluster name; it is not a cluster.
	if report.Cluster.Name != "" {
		fmt.Fprintf(w, "cluster: %s discovered endpoints=%d\n", report.Cluster.Name, len(report.Cluster.Discovered))
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
	if result := report.Compatibility; result != nil {
		fmt.Fprintf(w, "compatibility: %s (advisory only) cli=%s", result.Status, result.CLIVersion)
		if result.Reason != "" {
			fmt.Fprintf(w, " reason=%s", result.Reason)
		}
		if result.Error != "" {
			fmt.Fprintf(w, " error=%s", result.Error)
		}
		fmt.Fprintln(w)
		for _, edge := range result.Machines {
			fmt.Fprintf(w, "  %s: sdk=%q %s", edge.MachineID, edge.SDKVersion, edge.Status)
			for _, bounds := range edge.SupportedRanges {
				fmt.Fprintf(w, " supported=%s..%s (inclusive)", bounds.Min, bounds.Max)
			}
			fmt.Fprintln(w)
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
		fmt.Fprintf(w, "  %s: %s endpoints=%d/%d reachable unique brokers=%d%s\n", clusterLabel, gateway.Status, gateway.Reachable, gateway.Configured, gateway.Brokers, unidentifiedNote(gateway.UnidentifiedEndpoints))
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
