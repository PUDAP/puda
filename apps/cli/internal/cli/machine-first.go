package cli

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/spf13/cobra"
)

// machineFirstCmd is a subcommand of machineCmd for first machine operations
var machineFirstCmd = &cobra.Command{
	Use:   "first",
	Short: "Liquid handling robot, motion system, and camera",
	Long: `Liquid handling robot, motion system, and camera for the first machine.

For help on subcommands, add --help after: "puda machine first --help"`,
}

// machineFirstHelpCmd is a subcommand that shows Python help for FirstMachine
var machineFirstHelpCmd = &cobra.Command{
	Use:   "help",
	Short: "Show Python help documentation for FirstMachine",
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

// init registers the first machine command and its subcommands
func init() {
	machineCmd.AddCommand(machineFirstCmd)
	machineFirstCmd.AddCommand(machineFirstHelpCmd)
}
