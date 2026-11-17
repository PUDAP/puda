package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// logoutCmd clears the user identity from the global config.
var logoutCmd = &cobra.Command{
	Use:   "logout",
	Short: "Clear your PUDA username",
	Long: `Clear the logged-in identity from the global config.

NATS profiles and other settings are kept. The next command that needs an
identity creates a new default identity from your OS username.`,
	RunE: runLogout,
}

// runLogout clears only the user section of the global config.
func runLogout(cmd *cobra.Command, args []string) error {
	cfg, err := puda.ReadGlobalConfig()
	if err != nil {
		return err
	}
	if cfg.User.Username == "" || cfg.User.Default {
		fmt.Fprintln(cmd.OutOrStdout(), "You are not logged in.")
		return nil
	}

	username := cfg.User.Username
	cfg.User = puda.ConfigUser{}
	if err := puda.SaveGlobalConfig(cfg); err != nil {
		return err
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Logged out %s. Profiles and other settings were kept.\n", username)
	return nil
}
