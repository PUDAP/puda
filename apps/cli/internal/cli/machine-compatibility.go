package cli

import (
	"fmt"
	"io"
	"time"

	natsio "github.com/nats-io/nats.go"

	compatibility "github.com/PUDAP/puda"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/spf13/cobra"
)

// writeMachineDiscovery preserves discovery output and errors. Advisories use
// only successful pongs, and stderr failures never change command success.
func writeMachineDiscovery(cmd *cobra.Command, results []pudanats.PingResult, byMachine map[string][]pudanats.LivestreamRef, human, list bool) error {
	var err error
	if list {
		err = writeListResults(cmd.OutOrStdout(), results, byMachine, human)
	} else {
		err = writeInfoResults(cmd.OutOrStdout(), results, byMachine, human)
	}
	if err != nil {
		return err
	}
	writeCompatibilityWarnings(cmd.ErrOrStderr(), results, Version, compatibility.Bundled(), "")
	return nil
}

// writeCompatibilityWarnings shares range evaluation/formatting across list,
// info, healthcheck and update. Only update supplies a current CLI for comparison.
func writeCompatibilityWarnings(w io.Writer, results []pudanats.PingResult, version string, policy compatibility.Policy, currentVersion string) {
	seen := make(map[string]bool)
	for _, edge := range results {
		if edge.Status != "pong" || seen[edge.MachineID] {
			continue
		}
		seen[edge.MachineID] = true
		result := policy.Evaluate(version, edge.SDKVersion)
		warning := result.Warning(version, edge.MachineID, edge.SDKVersion)
		if warning == "" {
			continue
		}
		fmt.Fprint(w, warning)
		if currentVersion != "" && result.Status == compatibility.Unsupported {
			change := "current compatibility unknown; cannot determine whether update introduces this mismatch"
			switch compatibility.Bundled().Evaluate(currentVersion, edge.SDKVersion).Status {
			case compatibility.Supported:
				change = "newly unsupported by target (currently declared supported)"
			case compatibility.Unsupported:
				change = "already outside the supported range of current CLI"
			}
			fmt.Fprintf(w, "  CLI %q -> %q: %s.\n", currentVersion, version, change)
		}
	}
}

// writeFleetCompatibility is fresh bounded discovery, never a stored inventory
// or an assertion that all connected/offline machines have been checked.
func writeFleetCompatibility(w io.Writer, servers string, timeout time.Duration, version string, policy compatibility.Policy, currentVersion string) {
	if timeout <= 0 {
		timeout = 2 * time.Second
	}
	nc, err := pudanats.Connect(servers, natsio.Timeout(timeout), natsio.NoReconnect())
	if err != nil {
		fmt.Fprintf(w, "Python SDK compatibility not checked: fleet discovery unavailable: %v (advisory only).\n", err)
		return
	}
	defer nc.Close()
	results, err := pudanats.ListMachinePongs(nc, timeout)
	if err != nil {
		fmt.Fprintf(w, "Python SDK compatibility not checked: fleet discovery unavailable: %v (advisory only).\n", err)
		return
	}
	if len(results) == 0 {
		fmt.Fprintf(w, "Python SDK compatibility not checked: no edges responded within %s (advisory only).\n", timeout)
		return
	}
	writeCompatibilityWarnings(w, results, version, policy, currentVersion)
}
