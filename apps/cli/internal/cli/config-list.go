package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// configListCmd lists the current PUDA configuration values.
var configListCmd = &cobra.Command{
	Use:   "list",
	Short: "List PUDA CLI configuration values",
	Long:  "Display all configuration values in key=value format.",
	RunE:  runConfigList,
}

// runConfigList displays the configuration values in key=value format.
func runConfigList(cmd *cobra.Command, args []string) error {
	// Try to load project config first, fall back to global config
	cfg, err := puda.LoadProjectConfig()
	if err != nil {
		// If not in a project, just show global config
		globalCfg, err := puda.LoadGlobalConfig()
		if err != nil {
			return fmt.Errorf("failed to load configuration: %w", err)
		}
		fmt.Fprintf(cmd.OutOrStdout(), "user.user_id=%s\n", globalCfg.User.UserID)
		fmt.Fprintf(cmd.OutOrStdout(), "user.username=%s\n", globalCfg.User.Username)
		return nil
	}

	fmt.Fprintf(cmd.OutOrStdout(), "user.user_id=%s\n", cfg.User.UserID)
	fmt.Fprintf(cmd.OutOrStdout(), "user.username=%s\n", cfg.User.Username)
	fmt.Fprintf(cmd.OutOrStdout(), "endpoints.nats=%s\n", cfg.Endpoints.NATS)
	fmt.Fprintf(cmd.OutOrStdout(), "database.path=%s\n", cfg.Database.Path)
	fmt.Fprintf(cmd.OutOrStdout(), "project_root=%s\n", cfg.ProjectRoot)

	return nil
}
