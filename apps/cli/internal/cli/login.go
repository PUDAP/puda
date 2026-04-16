package cli

import (
	"bufio"
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

// runLogin executes the login flow: prompt for username and write config file.
func runLogin(cmd *cobra.Command, args []string) error {
	configPath, err := puda.GlobalConfigPath()
	if err != nil {
		return err
	}

	// If a config file already exists, assume the user is already logged in.
	if _, err := os.Stat(configPath); err == nil {
		fmt.Fprintln(cmd.OutOrStdout(), "You are already logged in.")
		return nil
	} else if !os.IsNotExist(err) {
		return fmt.Errorf("failed to check existing config file: %w", err)
	}

	reader := bufio.NewReader(os.Stdin)

	fmt.Fprint(cmd.OutOrStdout(), "Enter username: ")
	usernameRaw, err := reader.ReadString('\n')
	if err != nil {
		return fmt.Errorf("failed to read username: %w", err)
	}
	username := strings.TrimSpace(usernameRaw)
	if username == "" {
		return fmt.Errorf("username cannot be empty")
	}

	// Simulate talking to a backend auth service to obtain user ID and NATS endpoints.
	fmt.Fprintln(cmd.OutOrStdout(), "Contacting PUDA authentication service...")
	fmt.Fprintf(cmd.OutOrStdout(), "Authenticating user %q...\n", username)

	var cfg puda.GlobalConfig
	cfg.User.Username = username
	cfg.User.UserID = uuid.NewString()
	cfg.ActiveProfile = "bears"

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
