package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// natsProtocolSendCmd is a subcommand of natsProtocolCmd that sends a protocol to machines via NATS
//
// Usage: puda nats protocol send --file <path>
var natsProtocolSendCmd = &cobra.Command{
	Use:   "send",
	Short: "Send a protocol to machines via NATS",
	Long: `Send a protocol to machines via NATS using CommandService.
Loads a protocol from a JSON file and sends commands sequentially, stopping on first error.

The JSON file must be an object with the following structure:
  {
    "user_id": "user123",
    "username": "john",
    "description": "Test run",
    "commands": [...]
  }

The user_id and username must be provided in the JSON file.

Requires a .env file in the project root with:
  NATS_SERVERS: Comma-separated list of NATS server URLs

Example:
  puda nats protocol send --file protocol.json`,
	RunE: sendProtocol,
}

// Protocol send flags
var (
	protocolFilePath string
	timeout          int
	natsServers      string
)

// init registers flags for the send command
func init() {
	natsProtocolSendCmd.Flags().StringVarP(&protocolFilePath, "file", "f", "", "Path to JSON file containing protocol (required)")
	natsProtocolSendCmd.Flags().IntVarP(&timeout, "timeout", "t", 120, "Timeout per command in seconds (default: 120)")
	natsProtocolSendCmd.Flags().StringVar(&natsServers, "nats-servers", "", "Comma-separated NATS server URLs - overrides NATS_SERVERS from .env")
	natsProtocolSendCmd.MarkFlagRequired("file")
}

// sendProtocol executes the send command
func sendProtocol(cmd *cobra.Command, args []string) error {
	// Load protocol JSON from file
	protocolJSON, err := puda.LoadProtocol(protocolFilePath)
	if err != nil {
		return fmt.Errorf("failed to load protocol file: %w", err)
	}

	if err := nats.SendProtocol(protocolJSON, timeout, natsServers); err != nil {
		return fmt.Errorf("failed to run batch commands: %w", err)
	}
	return nil
}
