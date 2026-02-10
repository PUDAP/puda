package cli

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "puda",
	Short: "PUDA CLI - Command-line interface for PUDA",
	Long:  "PUDA CLI provides commands for the platform",
	Run: func(cmd *cobra.Command, args []string) {
		// Show help when no subcommand is provided
		cmd.Help()
	},
}

// Execute runs the root command
func Execute() error {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return err
	}
	return nil
}

// init registers all top-level commands with the root command
func init() {
	// Register top-level commands
	rootCmd.AddCommand(natsCmd)
	rootCmd.AddCommand(machineCmd)
	rootCmd.AddCommand(loginCmd)
	rootCmd.AddCommand(configCmd)
}
