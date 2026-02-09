package cli

import (
	"fmt"
	"os"
	"os/exec"

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

// init registers the help subcommands
func init() {
	machineBiologicHelpCmd.AddCommand(machineBiologicHelpCommandsCmd)
}
