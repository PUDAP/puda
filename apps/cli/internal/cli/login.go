package cli

import (
	"fmt"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
)

// loginCmd sets the user identity recorded in PUDA command messages.
var loginCmd = &cobra.Command{
	Use:   "login",
	Short: "Set your PUDA username",
	Long: `Set the username recorded with machine commands and runs.

Without login, PUDA uses a default identity derived from your OS username.
Logging in replaces that default username and keeps its user ID. No server
is contacted; the identity is stored in the global config file.`,
	RunE: runLogin,
}

var loginUsername string

func init() {
	loginCmd.Flags().StringVarP(&loginUsername, "username", "u", "", "Username for the PUDA account")
}

// runLogin stores the chosen username, replacing a default identity.
func runLogin(cmd *cobra.Command, args []string) error {
	cfg, err := puda.ReadGlobalConfig()
	if err != nil {
		return err
	}
	if cfg.User.Username != "" && !cfg.User.Default {
		fmt.Fprintf(cmd.OutOrStdout(), "You are already logged in as %s.\n", cfg.User.Username)
		return nil
	}

	username := strings.TrimSpace(loginUsername)
	if username == "" {
		return fmt.Errorf("username is required; pass --username <name>")
	}

	cfg.User.Username = username
	cfg.User.Default = false
	if strings.TrimSpace(cfg.User.UserID) == "" {
		cfg.User.UserID = uuid.NewString()
	}
	if err := puda.SaveGlobalConfig(cfg); err != nil {
		return err
	}

	configPath, err := puda.GlobalConfigPath()
	if err != nil {
		return err
	}
	fmt.Fprintf(cmd.OutOrStdout(), "Logged in as %s (user ID %s).\n", username, cfg.User.UserID)
	fmt.Fprintf(cmd.OutOrStdout(), "Saved puda configuration to %s\n", configPath)
	return nil
}
