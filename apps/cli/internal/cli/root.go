package cli

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "puda",
	Short: "PUDA CLI - Command-line interface for PUDA",
	Long:  "PUDA CLI provides commands for interacting with PUDA machines via NATS",
}

// Execute runs the root command
func Execute() error {
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		return err
	}
	return nil
}

func init() {
	rootCmd.AddCommand(natsCmd)
}

