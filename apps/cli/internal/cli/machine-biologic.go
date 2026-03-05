package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

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

// machineBiologicHelpCommandsCmd shows available commands for BiologicMachine
var machineBiologicHelpCommandsCmd = &cobra.Command{
	Use:   "commands",
	Short: "Show available commands",
	Long: `Show Python help documentation for BiologicMachine class.

This command calls Python's help() function on puda_drivers.machines.Biologic
to display all available methods and their documentation.`,
	Run: func(cmd *cobra.Command, args []string) {
		if err := puda.ShowPublicMethods("puda_drivers.machines", "Biologic"); err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
	},
}

// init registers the biologic machine command and its subcommands
func init() {
	machineCmd.AddCommand(machineBiologicCmd)
	machineBiologicCmd.AddCommand(machineBiologicHelpCmd)
	machineBiologicHelpCmd.AddCommand(machineBiologicHelpCommandsCmd)
}
