package cli

import (
	"fmt"
	"os"
	"os/exec"

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

// machineBiologicHelpCmd is a subcommand that shows Python help for BiologicMachine
var machineBiologicHelpCmd = &cobra.Command{
	Use:   "help",
	Short: "Show Python help documentation for BiologicMachine",
	Long: `Show Python help documentation for BiologicMachine class.

This command calls Python's help() function on puda_drivers.machines.Biologic
to display all available methods and their documentation.`,
	Run: func(cmd *cobra.Command, args []string) {
		// Call Python help() on BiologicMachine
		pythonCmd := exec.Command("python3", "-c", "from puda_drivers.machines import Biologic; help(Biologic)")
		output, err := pythonCmd.CombinedOutput()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error running Python help: %v\n", err)
			fmt.Fprintf(os.Stderr, "Output: %s\n", string(output))
			os.Exit(1)
		}
		fmt.Print(string(output))
	},
}

// init registers the biologic machine command and its subcommands
func init() {
	machineCmd.AddCommand(machineBiologicCmd)
	machineBiologicCmd.AddCommand(machineBiologicHelpCmd)
}
