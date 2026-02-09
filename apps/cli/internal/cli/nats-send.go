package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/spf13/cobra"
)

// sendCmd is a subcommand of natsCmd that sends commands to machines via NATS
//
// Usage: puda nats send --file <path>
var natsSendCmd = &cobra.Command{
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
	RunE: sendBatchCommands,
}

// Command flags
var (
	commandsFile string
	timeout      int
	userID       string
	username     string
	natsServers  string
)

// init registers flags for the send command
func init() {
	natsSendCmd.Flags().StringVarP(&commandsFile, "file", "f", "", "Path to JSON file containing array of commands (required)")
	natsSendCmd.Flags().IntVarP(&timeout, "timeout", "t", 120, "Timeout per command in seconds (default: 120)")
	natsSendCmd.Flags().StringVar(&userID, "user-id", "", "User ID (UUID string) - overrides USER_ID from .env")
	natsSendCmd.Flags().StringVar(&username, "username", "", "Username - overrides USERNAME from .env")
	natsSendCmd.Flags().StringVar(&natsServers, "nats-servers", "", "Comma-separated NATS server URLs - overrides NATS_SERVERS from .env")
	natsSendCmd.MarkFlagRequired("file")
}

// sendBatchCommands executes the send command
func sendBatchCommands(cmd *cobra.Command, args []string) error {
	if err := nats.SendBatchCommands(commandsFile, timeout, userID, username, natsServers); err != nil {
		return fmt.Errorf("failed to run batch commands: %w", err)
	}
	return nil
}
