package cli

import "github.com/spf13/cobra"

// natsCmd is the top-level command for NATS-related operations
//
// Subcommands:
//   - command: Command operations (send, validate)
//   - status: Get machine status from NATS Key-Value store
var natsCmd = &cobra.Command{
	Use:   "nats",
	Short: "Communication using nats.io",
	Long: `Commands for interacting with machines via NATS

For help on subcommands, add --help after: "puda nats command send --help"`,
}

// init registers all NATS subcommands
func init() {
	natsCmd.AddCommand(natsCommandCmd)
	natsCmd.AddCommand(natsStatusCmd)
}
