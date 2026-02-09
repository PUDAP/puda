package cli

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

// machineCmd is the top-level command for machine-related operations
var machineCmd = &cobra.Command{
	Use:   "machine",
	Short: "Machine operations",
	Long: `Commands for machine operations

For help on subcommands, add --help after: "puda machine first --help"`,
	Run: func(cmd *cobra.Command, args []string) {
		// List available machines dynamically from registered subcommands
		subcommands := cmd.Commands()
		if len(subcommands) == 0 {
			fmt.Fprintf(os.Stderr, "No machines available.\n")
			return
		}

		fmt.Fprintf(os.Stdout, "Available machines:\n\n")
		for _, subcmd := range subcommands {
			fmt.Fprintf(os.Stdout, "  %-10s - %s\n", subcmd.Use, subcmd.Short)
		}
		fmt.Fprintf(os.Stdout, "\nUse 'puda machine <machine-name> --help' for more information.\n")
	},
}

// init registers all machine subcommands
func init() {
	// Subcommands register themselves in their respective files
}
