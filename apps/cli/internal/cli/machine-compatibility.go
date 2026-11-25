package cli

import (
	"fmt"
	"io"

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
	writeCompatibilityWarnings(cmd.ErrOrStderr(), results)
	return nil
}

// writeCompatibilityWarnings prints one line per responding edge whose
// protocol_version this CLI does not support.
func writeCompatibilityWarnings(w io.Writer, results []pudanats.PingResult) {
	seen := make(map[string]bool)
	for _, edge := range results {
		if edge.Status != "pong" || seen[edge.MachineID] {
			continue
		}
		seen[edge.MachineID] = true
		if pudanats.ClassifyProtocol(edge.ProtocolVersion) == pudanats.ProtocolSupported {
			continue
		}
		fmt.Fprintf(w, "warning: machine %s speaks edge protocol %s; this CLI supports %s (update the edge's PUDA SDK)\n",
			edge.MachineID, pudanats.ProtocolLabel(edge.ProtocolVersion), pudanats.SupportedProtocol)
	}
}
