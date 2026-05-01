package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
)

// loginCmd configures the user's identity for PUDA CLI.
var loginCmd = &cobra.Command{
	Use:   "login",
	Short: "Log in to a PUDA account",
	Long: `Log in to a PUDA account.

	Authenticate with a PUDA host and retrieve user configuration.
`,
	RunE: runLogin,
}

var loginUsername string

func init() {
	loginCmd.Flags().StringVarP(&loginUsername, "username", "u", "", "Username for the PUDA account")
}

// runLogin executes the login flow: read username from flag and write config file.
func runLogin(cmd *cobra.Command, args []string) error {
	configPath, err := puda.GlobalConfigPath()
	if err != nil {
		return err
	}

	// If a config file already exists, assume the user is already logged in.
	if _, err := os.Stat(configPath); err == nil {
		data, err := os.ReadFile(configPath)
		if err != nil {
			return logoutInvalidLogin(configPath, fmt.Errorf("failed to read existing config file: %w", err))
		}

		var cfg puda.GlobalConfig
		if err := json.Unmarshal(data, &cfg); err != nil {
			return logoutInvalidLogin(configPath, fmt.Errorf("failed to parse existing config file: %w", err))
		}
		if cfg.User.Username == "" {
			return logoutInvalidLogin(configPath, fmt.Errorf("username is missing in existing config file %s", configPath))
		}

		fmt.Fprintf(cmd.OutOrStdout(), "You are already logged in as %s.\n", cfg.User.Username)
		return nil
	} else if !os.IsNotExist(err) {
		return fmt.Errorf("failed to check existing config file: %w", err)
	}

	username := strings.TrimSpace(loginUsername)
	if username == "" {
		return fmt.Errorf("username is required; pass --username <name>")
	}

	// Simulate talking to a backend auth service to obtain user ID and NATS endpoints.
	fmt.Fprintln(cmd.OutOrStdout(), "Contacting PUDA authentication service...")
	fmt.Fprintf(cmd.OutOrStdout(), "Authenticating user %q...\n", username)

	var cfg puda.GlobalConfig
	cfg.User.Username = username
	cfg.User.UserID = uuid.NewString()
	cfg.ActiveEnv = "bears"

	fmt.Fprintln(cmd.OutOrStdout(), "Fetching user configuration...")

	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	if err := os.WriteFile(configPath, data, 0o600); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}

	fmt.Fprintln(cmd.OutOrStdout(), "Login successful.")
	fmt.Fprintf(cmd.OutOrStdout(), "Saved puda configuration to %s\n", configPath)
	return nil
}

func logoutInvalidLogin(configPath string, cause error) error {
	if err := os.Remove(configPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("%w; failed to log out user: %v", cause, err)
	}

	return fmt.Errorf("%w; you have been logged out, please log in again", cause)
}
