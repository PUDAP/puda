package cli

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// protocolValidateCmd is a subcommand of protocolCmd that validates a protocol JSON file
//
// Usage: puda protocol validate --file <path>
var protocolValidateCmd = &cobra.Command{
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
	protocolValidateCmd.Flags().StringVarP(&protocolFilePath, "file", "f", "", "Path to JSON file (required)")
	protocolValidateCmd.MarkFlagRequired("file")
}

// validateProtocol executes the validate command
func validateProtocol(cmd *cobra.Command, args []string) error {
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
	validationErrors, err := puda.ValidateProtocol(&protocolFile)

	// Print file metadata
	if protocolFile.UserID != "" {
		fmt.Fprintf(os.Stdout, "  user_id: %s\n", protocolFile.UserID)
	}
	if protocolFile.Username != "" {
		fmt.Fprintf(os.Stdout, "  username: %s\n", protocolFile.Username)
	}
	if protocolFile.Description != "" {
		fmt.Fprintf(os.Stdout, "  description: %s\n", protocolFile.Description)
	}

	if err != nil {
		// Print validation errors
		fmt.Fprintf(os.Stderr, "✗ Validation failed: %d error(s) found\n\n", len(validationErrors))
		for _, verr := range validationErrors {
			fmt.Fprintf(os.Stderr, "  Command #%d: %s - %s\n", verr.CommandIndex+1, verr.Field, verr.Message)
		}
		return err
	}

	// Validation passed
	fmt.Fprintf(os.Stdout, "✓ Validation passed: %d command(s) are valid\n", len(protocolFile.Commands))
	return nil
}
