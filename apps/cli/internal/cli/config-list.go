package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// configListCmd lists the current PUDA configuration values.
var configListCmd = &cobra.Command{
	Use:   "list",
	Short: "List user config",
	Long:  "Display the current user identity. user.default=true means it was derived from the OS username; run puda login to choose a username.",
	RunE:  runConfigList,
}

// runConfigList displays the configuration values in key=value format.
func runConfigList(cmd *cobra.Command, args []string) error {
	cfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}
	fmt.Fprintf(cmd.OutOrStdout(), "user.user_id=%s\n", cfg.User.UserID)
	fmt.Fprintf(cmd.OutOrStdout(), "user.username=%s\n", cfg.User.Username)
	fmt.Fprintf(cmd.OutOrStdout(), "user.default=%t\n", cfg.User.Default)
	return nil
}
