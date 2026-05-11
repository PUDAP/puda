package cli

import "github.com/spf13/cobra"

// protocolCmd is the parent command for protocol-related operations
//
// Subcommands:
//   - run: Run a protocol on machines via NATS
//   - validate: Validate a protocol JSON file
var protocolCmd = &cobra.Command{
	Use:   "protocol",
	Short: "Protocol operations",
	Long: `Commands for working with protocols via NATS.

Subcommands:
  run      - Run a puda protocol via NATS
  validate - Validate a protocol JSON file

For help on subcommands, add --help after: "puda protocol run --help"`,
}

// init registers all protocol subcommands
func init() {
	protocolCmd.AddCommand(protocolRunCmd)
	protocolCmd.AddCommand(protocolValidateCmd)
}
