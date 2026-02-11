package cli

import "github.com/spf13/cobra"

// configCmd manages PUDA CLI configuration.
var configCmd = &cobra.Command{
	Use:   "config",
	Short: "Manage PUDA CLI configuration",
	Long:  "Manage PUDA CLI configuration. Use subcommands to list or edit configuration.",
}

// init registers all config subcommands
func init() {
	configCmd.AddCommand(configListCmd)
	configCmd.AddCommand(configEditCmd)
}
