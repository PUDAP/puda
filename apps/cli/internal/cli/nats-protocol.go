package cli

import "github.com/spf13/cobra"

// natsProtocolCmd is the parent command for protocol-related operations
//
// Subcommands:
//   - send: Send a protocol to machines via NATS
//   - validate: Validate a protocol JSON file
var natsProtocolCmd = &cobra.Command{
	Use:   "protocol",
	Short: "Protocol operations for NATS",
	Long: `Commands for working with protocols via NATS.

Subcommands:
  send     - Send a protocol to machines via NATS
  validate - Validate a protocol JSON file

For help on subcommands, add --help after: "puda nats protocol send --help"`,
}

// init registers all protocol subcommands
func init() {
	natsProtocolCmd.AddCommand(natsProtocolSendCmd)
	natsProtocolCmd.AddCommand(natsProtocolValidateCmd)
}
