package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

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

// init registers the help subcommands
func init() {
	machineBiologicHelpCmd.AddCommand(machineBiologicHelpCommandsCmd)
}
