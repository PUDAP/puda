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

// loginConfig represents the structure of the login configuration file.
type loginConfig struct {
	User struct {
		Username string `json:"username"`
		UserID   string `json:"userid"`
	} `json:"user"`
	Endpoints struct {
		NATS string `json:"nats"`
	} `json:"endpoints"`
}

// loginCmd configures the user's identity for PUDA CLI.
// It prompts for a username and writes a JSON configuration file to:
//
//	~/.puda/config.json
var loginCmd = &cobra.Command{
	Use:   "login",
	Short: "Configure your PUDA CLI user identity",
	Long: `Login to PUDA by setting your username.

This command generates a configuration file at ~/.puda/config.json
containing your username, a generated user ID, and the default NATS
endpoint used by the CLI.
`,
	RunE: runLogin,
}

// runLogin executes the login flow: prompt for username and write config file.
func runLogin(cmd *cobra.Command, args []string) error {
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

	userID := uuid.NewString()

	configPath, err := puda.ConfigPath()
	if err != nil {
		return err
	}

	var cfg loginConfig
	cfg.User.Username = username
	cfg.User.UserID = userID
	cfg.Endpoints.NATS = "nats://100.109.131.12:4222,nats://100.109.131.12:4223,nats://100.109.131.12:4224"

	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	if err := os.WriteFile(configPath, data, 0o600); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Saved puda configuration to %s\n", configPath)
	return nil
}
