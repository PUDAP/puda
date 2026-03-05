package cli

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

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

// machineFirstHelpCommandsCmd shows available commands for FirstMachine
var machineFirstHelpCommandsCmd = &cobra.Command{
	Use:   "commands",
	Short: "Show available commands",
	Long: `Show Python help documentation for FirstMachine class.

This command calls Python's help() function on puda_drivers.machines.First
to display all available methods and their documentation.`,
	Run: func(cmd *cobra.Command, args []string) {
		if err := puda.ShowPublicMethods("puda_drivers.machines", "First"); err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
	},
}

// machineFirstHelpLabwareCmd shows available labware
var machineFirstHelpLabwareCmd = &cobra.Command{
	Use:   "labware",
	Short: "Show available labware",
	Long: `Show available labware from puda_drivers.labware.

This command calls get_available_labware() to display all available labware.`,
	Run: func(cmd *cobra.Command, args []string) {
		// Ensure Python module is available
		if err := puda.EnsurePythonModule("puda_drivers"); err != nil {
			fmt.Fprintf(os.Stderr, "Error ensuring Python module: %v\n", err)
			os.Exit(1)
		}

		labwareCmd := exec.Command("python3", "-c", "from puda_drivers.labware import get_available_labware; print(get_available_labware())")
		labwareOutput, err := labwareCmd.CombinedOutput()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error getting available labware: %v\n", err)
			fmt.Fprintf(os.Stderr, "Output: %s\n", string(labwareOutput))
			os.Exit(1)
		}
		fmt.Print(string(labwareOutput))
	},
}

// init registers the first machine command and its subcommands
func init() {
	machineCmd.AddCommand(machineFirstCmd)
	machineFirstCmd.AddCommand(machineFirstHelpCmd)
	machineFirstHelpCmd.AddCommand(machineFirstHelpCommandsCmd)
	machineFirstHelpCmd.AddCommand(machineFirstHelpLabwareCmd)
}
