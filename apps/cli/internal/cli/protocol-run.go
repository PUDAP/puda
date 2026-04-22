package cli

import (
	"encoding/json"
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// protocolRunCmd is a subcommand of protocolCmd that runs a protocol on machines via NATS
//
// Usage: puda protocol run --file <path>
var protocolRunCmd = &cobra.Command{
	Use:   "run",
	Short: "Run a protocol on machines via NATS",
	Long: `Run a protocol on machines via NATS.
Loads a protocol JSON file from the given path and runs commands sequentially, stopping on first error. 

Optional: --nats-servers to override NATS server URLs in config file.

Example:
  puda protocol run --file protocol.json`,
	RunE: runProtocol,
}

// Protocol run flags
var (
	protocolFilePath string
	natsServers      string
	startStep        int
)

// init registers flags for the run command
func init() {
	protocolRunCmd.Flags().StringVarP(&protocolFilePath, "file", "f", "", "Path to JSON file containing protocol (required)")
	protocolRunCmd.Flags().StringVar(&natsServers, "nats-servers", "", "Optional: Comma-separated NATS server URLs - overrides active env")
	protocolRunCmd.Flags().IntVar(&startStep, "start-step", 1, "Optional: step number to start running commands from")
	protocolRunCmd.MarkFlagRequired("file")
}

// runProtocol executes the run command
func runProtocol(cmd *cobra.Command, args []string) error {
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
		return err
	}
	defer store.Disconnect()

	err = store.InsertProtocol(protocolFile)
	if err != nil {
		return fmt.Errorf("failed to insert protocol into database: %w", err)
	}

	if err := nats.RunProtocol(&protocolFile, natsServers, startStep); err != nil {
		return fmt.Errorf("failed to run protocol: %w", err)
	}
	return nil
}
