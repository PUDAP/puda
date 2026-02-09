package cli

import "github.com/spf13/cobra"

// machineFirstCmd is a subcommand of machineCmd for first machine operations
var machineFirstCmd = &cobra.Command{
	Use:   "first",
	Short: "Liquid handling robot, motion system, and camera",
	Long: `Liquid handling robot, motion system, and camera for the first machine.

For help on subcommands, add --help after: "puda machine first --help"`,
}

// machineFirstHelpCmd is a subcommand that shows help information
var machineFirstHelpCmd = &cobra.Command{
	Use:   "help",
	Short: "Show help information for FirstMachine",
	Long: `Show help information for FirstMachine.

Subcommands:
  commands - Show available commands/methods for FirstMachine
  labware  - Show available labware`,
}

// init registers the first machine command and its subcommands
func init() {
	machineCmd.AddCommand(machineFirstCmd)
	machineFirstCmd.AddCommand(machineFirstHelpCmd)
}
