package cli

import (
	"fmt"
	"io"
	"time"

	compatibility "github.com/PUDAP/puda"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
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

The active profile's gateway_servers are client URLs in a
remote cluster expected through a NATS gateway. Those remotes are probed and
reported separately; a different cluster name is expected and is not degraded.
JetStream is reported per cluster, not blended.

A fresh fleet ping checks all responding edges' advertised Python SDK versions
against the bundled compatibility policy. Advisories go to stderr only and never
change the NATS report or exit status. No replies or failed discovery means
compatibility was not checked; offline edges cannot be evaluated.

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
	if err := writeHealthReport(cmd.OutOrStdout(), report, healthcheckHuman); err != nil {
		return err
	}
	writeHealthcheckCompatibility(cmd.ErrOrStderr(), servers, healthcheckTimeout)
	if report.Status != pudanats.HealthOK {
		return fmt.Errorf("NATS healthcheck %s", report.Status)
	}
	return nil
}

// writeHealthcheckCompatibility is advisory only: fleet discovery must not change
// the NATS health report or exit status, including when discovery is unavailable.
func writeHealthcheckCompatibility(w io.Writer, servers string, timeout time.Duration) {
	writeFleetCompatibility(w, servers, timeout, Version, compatibility.Bundled(), "")
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

	fmt.Fprintf(w, "status: %s\n", report.Status)
	fmt.Fprintf(w, "servers: %d/%d reachable\n", report.Cluster.Reachable, report.Cluster.Configured)
	for _, server := range report.Servers {
		if server.Status != "ok" {
			fmt.Fprintf(w, "  %s: failed: %s\n", server.URL, server.Error)
			continue
		}
		fmt.Fprintf(
			w,
			"  %s: ok %.3fms name=%s cluster=%s js=%t version=%s\n",
			server.URL,
			server.RTTMS,
			server.Name,
			server.Cluster,
			server.JetStream,
			server.Version,
		)
	}
	clusterLabel := report.Cluster.Name
	if clusterLabel == "" {
		clusterLabel = "(none)"
	}
	fmt.Fprintf(w, "cluster: %s discovered=%d\n", clusterLabel, len(report.Cluster.Discovered))
	if report.JetStream.OK {
		fmt.Fprintf(
			w,
			"jetstream: ok streams=%d consumers=%d memory=%d storage=%d\n",
			report.JetStream.Streams,
			report.JetStream.Consumers,
			report.JetStream.Memory,
			report.JetStream.Storage,
		)
	} else {
		fmt.Fprintf(w, "jetstream: failed: %s\n", report.JetStream.Error)
	}
	if len(report.Gateways) == 0 {
		return nil
	}
	fmt.Fprintf(w, "gateways: %d\n", len(report.Gateways))
	for _, gateway := range report.Gateways {
		clusterLabel := gateway.Cluster
		if clusterLabel == "" {
			clusterLabel = "(none)"
		}
		fmt.Fprintf(w, "  %s: %s %d/%d\n", clusterLabel, gateway.Status, gateway.Reachable, gateway.Configured)
		for _, server := range gateway.Servers {
			if server.Status != "ok" {
				fmt.Fprintf(w, "    %s: failed: %s\n", server.URL, server.Error)
				continue
			}
			fmt.Fprintf(
				w,
				"    %s: ok %.3fms name=%s cluster=%s js=%t version=%s\n",
				server.URL,
				server.RTTMS,
				server.Name,
				server.Cluster,
				server.JetStream,
				server.Version,
			)
		}
		if gateway.JetStream.OK {
			fmt.Fprintf(
				w,
				"    jetstream: ok streams=%d consumers=%d memory=%d storage=%d\n",
				gateway.JetStream.Streams,
				gateway.JetStream.Consumers,
				gateway.JetStream.Memory,
				gateway.JetStream.Storage,
			)
		} else {
			fmt.Fprintf(w, "    jetstream: failed: %s\n", gateway.JetStream.Error)
		}
	}
	return nil
}
