package cli

import "github.com/spf13/cobra"

// natsCommandCmd is the parent command for command-related operations
//
// Subcommands:
//   - send: Send a sequence of commands to machines via NATS
//   - validate: Validate a commands JSON file
var natsCommandCmd = &cobra.Command{
	Use:   "command",
	Short: "Command operations for NATS",
	Long: `Commands for working with machine commands via NATS.

Subcommands:
  send     - Send a sequence of commands to machines via NATS
  validate - Validate a commands JSON file

For help on subcommands, add --help after: "puda nats command send --help"`,
}

// init registers all command subcommands
func init() {
	natsCommandCmd.AddCommand(natsCommandSendCmd)
	natsCommandCmd.AddCommand(natsCommandValidateCmd)
}

