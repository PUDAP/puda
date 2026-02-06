package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/spf13/cobra"
)

var (
	commandsFile string
	timeout      int
	userID       string
	username     string
	natsServers  string
)

var sendCmd = &cobra.Command{
	Use:   "send",
	Short: "Send a sequence of commands to machines via NATS",
	Long: `Send a sequence of commands to machines via NATS using CommandService.
Loads commands from a JSON file and sends them sequentially, stopping on first error.

Requires a .env file in the project root with:
  USER_ID: Unique identifier for the user (UUID string)
  USERNAME: Username of the person initiating the commands
  NATS_SERVERS: Comma-separated list of NATS server URLs

Example:
  puda nats send --file commands.json`,
	RunE: runBatchCommands,
}

func init() {
	sendCmd.Flags().StringVarP(&commandsFile, "file", "f", "", "Path to JSON file containing array of commands (required)")
	sendCmd.Flags().IntVarP(&timeout, "timeout", "t", 120, "Timeout per command in seconds (default: 120)")
	sendCmd.Flags().StringVar(&userID, "user-id", "", "User ID (UUID string) - overrides USER_ID from .env")
	sendCmd.Flags().StringVar(&username, "username", "", "Username - overrides USERNAME from .env")
	sendCmd.Flags().StringVar(&natsServers, "nats-servers", "", "Comma-separated NATS server URLs - overrides NATS_SERVERS from .env")
	sendCmd.MarkFlagRequired("file")
}

func runBatchCommands(cmd *cobra.Command, args []string) error {
	if err := nats.RunBatchCommands(commandsFile, timeout, userID, username, natsServers); err != nil {
		return fmt.Errorf("failed to run batch commands: %w", err)
	}
	return nil
}
