package cli

import (
	"encoding/json"
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/db"
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
	Long: `Send a protocol to machines via NATS.
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
	RunE:         sendProtocol,
	SilenceUsage: true,
}

// Protocol send flags
var (
	protocolFilePath string
	natsServers      string
)

// init registers flags for the send command
func init() {
	natsProtocolSendCmd.Flags().StringVarP(&protocolFilePath, "file", "f", "", "Path to JSON file containing protocol (required)")
	natsProtocolSendCmd.Flags().StringVar(&natsServers, "nats-servers", "", "Comma-separated NATS server URLs - overrides NATS_SERVERS from .env")
	natsProtocolSendCmd.MarkFlagRequired("file")
}

// sendProtocol executes the send command
func sendProtocol(cmd *cobra.Command, args []string) error {
	// Load and parse protocol file
	protocolJSON, err := puda.LoadProtocol(protocolFilePath)
	if err != nil {
		return fmt.Errorf("failed to load protocol file: %w", err)
	}

	var protocolFile puda.ProtocolFile
	if err := json.Unmarshal(protocolJSON, &protocolFile); err != nil {
		return fmt.Errorf("failed to parse protocol JSON: %w", err)
	}

	// Validate protocol
	_, err = puda.ValidateProtocol(&protocolFile)
	if err != nil {
		return err // Error already formatted by ValidateProtocol
	}

	// Insert protocol into database
	store, err := db.Connect()
	if err != nil {
		return fmt.Errorf("failed to connect to database: %w", err)
	}
	defer store.Disconnect()

	err = store.InsertProtocol(protocolFile)
	if err != nil {
		return fmt.Errorf("failed to insert protocol into database: %w", err)
	}

	if err := nats.SendProtocol(&protocolFile, natsServers); err != nil {
		return fmt.Errorf("failed to run batch commands: %w", err)
	}
	return nil
}
