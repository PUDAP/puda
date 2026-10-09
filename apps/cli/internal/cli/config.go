package cli

import "github.com/spf13/cobra"

// configCmd manages PUDA CLI configuration.
var configCmd = &cobra.Command{
	Use:   "config",
	Short: "Manage user config",
	Long:  "Manage the logged-in user. Project settings are 'puda project config'.",
}

// init registers all config subcommands
func init() {
	configCmd.AddCommand(configListCmd)
	configCmd.AddCommand(configEditCmd)
	configCmd.AddCommand(configGetCmd)
	configCmd.AddCommand(configSetCmd)
}
