package cli

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/spf13/cobra"
)

// machineFirstHelpCommandsCmd shows available commands for FirstMachine
var machineFirstHelpCommandsCmd = &cobra.Command{
	Use:   "commands",
	Short: "Show available commands",
	Long: `Show Python help documentation for FirstMachine class.

This command calls Python's help() function on puda_drivers.machines.First
to display all available methods and their documentation.`,
	Run: func(cmd *cobra.Command, args []string) {
		// Call Python help() on FirstMachine
		pythonCmd := exec.Command("python3", "-c", "from puda_drivers.machines import First; help(First)")
		output, err := pythonCmd.CombinedOutput()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error running Python help: %v\n", err)
			fmt.Fprintf(os.Stderr, "Output: %s\n", string(output))
			os.Exit(1)
		}
		fmt.Print(string(output))
	},
}

// machineFirstHelpLabwareCmd shows available labware
var machineFirstHelpLabwareCmd = &cobra.Command{
	Use:   "labware",
	Short: "Show available labware",
	Long: `Show available labware from puda_drivers.labware.

This command calls get_available_labware() to display all available labware.`,
	Run: func(cmd *cobra.Command, args []string) {
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

// init registers the help subcommands
func init() {
	machineFirstHelpCmd.AddCommand(machineFirstHelpCommandsCmd)
	machineFirstHelpCmd.AddCommand(machineFirstHelpLabwareCmd)
}
