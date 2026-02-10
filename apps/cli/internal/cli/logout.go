package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// logoutCmd removes the PUDA configuration file, effectively logging the user out.
var logoutCmd = &cobra.Command{
	Use:   "logout",
	Short: "Log out of a PUDA account",
	Long: `Log out of a PUDA account

	This removes your configuration file and revokes your access token.`,
	RunE: runLogout,
}

// runLogout deletes the configuration file if it exists.
func runLogout(cmd *cobra.Command, args []string) error {
	configPath, err := puda.ConfigPath()
	if err != nil {
		return err
	}

	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		fmt.Fprintln(cmd.OutOrStdout(), "You are not logged in.")
		return nil
	}

	if err := os.Remove(configPath); err != nil {
		return fmt.Errorf("failed to remove config file: %w", err)
	}

	fmt.Fprintln(cmd.OutOrStdout(), "Logout successful")
	return nil
}
