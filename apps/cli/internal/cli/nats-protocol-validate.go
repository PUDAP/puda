package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// natsProtocolValidateCmd is a subcommand of natsProtocolCmd that validates a protocol JSON file
//
// Usage: puda nats protocol validate --file <path>
var natsProtocolValidateCmd = &cobra.Command{
	Use:   "validate",
	Short: "Validate a protocol JSON file",
	Long: `Validate a protocol JSON file to ensure it has the correct structure and required fields.

The JSON file must be an object with the following structure:
  {
    "user_id": "user123",
    "username": "john",
    "description": "Test run",
    "commands": [...]
  }

Checks:
  - Valid JSON format
  - Object structure with "commands" array field
  - Each command has required fields: name, machine_id, step_number
  - Params field is optional for commands

Example:
  puda nats protocol validate --file protocol.json`,
	RunE: validateProtocol,
}

// init registers flags for the validate command
func init() {
	natsProtocolValidateCmd.Flags().StringVarP(&protocolFilePath, "file", "f", "", "Path to JSON file (required)")
	natsProtocolValidateCmd.MarkFlagRequired("file")
}

// validateProtocol executes the validate command
func validateProtocol(cmd *cobra.Command, args []string) error {
	protocolFile, errors, err := puda.ValidateProtocol(protocolFilePath)
	if err != nil {
		return err
	}

	// Validate file metadata (optional fields)
	if protocolFile.UserID != "" {
		fmt.Fprintf(os.Stdout, "  user_id: %s\n", protocolFile.UserID)
	}
	if protocolFile.Username != "" {
		fmt.Fprintf(os.Stdout, "  username: %s\n", protocolFile.Username)
	}
	if protocolFile.Description != "" {
		fmt.Fprintf(os.Stdout, "  description: %s\n", protocolFile.Description)
	}

	if len(errors) == 0 {
		fmt.Fprintf(os.Stdout, "✓ Validation passed: %d command(s) are valid\n", len(protocolFile.Commands))
		return nil
	}

	// Print validation errors
	fmt.Fprintf(os.Stderr, "✗ Validation failed: %d error(s) found\n\n", len(errors))
	for _, err := range errors {
		fmt.Fprintf(os.Stderr, "  Command #%d: %s - %s\n", err.CommandIndex+1, err.Field, err.Message)
	}

	return fmt.Errorf("validation failed with %d error(s)", len(errors))
}
