package cli

import "github.com/spf13/cobra"

// natsProtocolCmd is the parent command for protocol-related operations
//
// Subcommands:
//   - run: Run a protocol on machines via NATS
//   - validate: Validate a protocol JSON file
var natsProtocolCmd = &cobra.Command{
	Use:   "protocol",
	Short: "Protocol operations for NATS",
	Long: `Commands for working with protocols via NATS.

Subcommands:
  run      - Run a puda protocol via NATS
  validate - Validate a protocol JSON file

For help on subcommands, add --help after: "puda nats protocol run --help"`,
}

// init registers all protocol subcommands
func init() {
	natsProtocolCmd.AddCommand(natsProtocolRunCmd)
	natsProtocolCmd.AddCommand(natsProtocolValidateCmd)
}
