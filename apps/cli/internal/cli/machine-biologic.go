package cli

import "github.com/spf13/cobra"

// machineBiologicCmd is a subcommand of machineCmd for biologic machine operations
var machineBiologicCmd = &cobra.Command{
	Use:   "biologic",
	Short: "Biologic electrochemical testing device",
	Long: `Biologic electrochemical testing device for the biologic machine.
This machine is used to test the electrochemical properties of materials.

For help on subcommands, add --help after: "puda machine biologic --help"`,
}

// machineBiologicHelpCmd is a subcommand that shows help information
var machineBiologicHelpCmd = &cobra.Command{
	Use:   "help",
	Short: "Show help information for BiologicMachine",
	Long: `Show help information for BiologicMachine.

Subcommands:
  commands - Show available commands/methods for BiologicMachine`,
}

// init registers the biologic machine command and its subcommands
func init() {
	machineCmd.AddCommand(machineBiologicCmd)
	machineBiologicCmd.AddCommand(machineBiologicHelpCmd)
}
