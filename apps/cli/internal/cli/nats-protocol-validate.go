package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
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

// Protocol validate flags
var (
	validateFile string
)

// init registers flags for the validate command
func init() {
	natsProtocolValidateCmd.Flags().StringVarP(&validateFile, "file", "f", "", "Path to JSON file (required)")
	natsProtocolValidateCmd.MarkFlagRequired("file")
}

// ValidationError represents a validation error
type ValidationError struct {
	CommandIndex int
	Field        string
	Message      string
}

// validateProtocol executes the validate command
func validateProtocol(cmd *cobra.Command, args []string) error {
	// Load commands from file with metadata - this validates the JSON structure
	commandResult, err := nats.LoadProtocol(validateFile)
	if err != nil {
		return fmt.Errorf("validation failed: %w", err)
	}

	commands := commandResult.Commands

	// Validate file metadata (optional fields)
	if commandResult.UserID != "" {
		fmt.Fprintf(os.Stdout, "  user_id: %s\n", commandResult.UserID)
	}
	if commandResult.Username != "" {
		fmt.Fprintf(os.Stdout, "  username: %s\n", commandResult.Username)
	}
	if commandResult.Description != "" {
		fmt.Fprintf(os.Stdout, "  description: %s\n", commandResult.Description)
	}

	// Validate commands
	errors := validateCommandStructure(commands)

	if len(errors) == 0 {
		fmt.Fprintf(os.Stdout, "✓ Validation passed: %d command(s) are valid\n", len(commands))
		return nil
	}

	// Print validation errors
	fmt.Fprintf(os.Stderr, "✗ Validation failed: %d error(s) found\n\n", len(errors))
	for _, err := range errors {
		fmt.Fprintf(os.Stderr, "  Command #%d: %s - %s\n", err.CommandIndex+1, err.Field, err.Message)
	}

	return fmt.Errorf("validation failed with %d error(s)", len(errors))
}

// validateCommandStructure validates the structure of commands
func validateCommandStructure(commands []puda.CommandRequest) []ValidationError {
	var errors []ValidationError

	for i, cmd := range commands {
		// Validate required fields
		if cmd.Name == "" {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "name",
				Message:      "required field is missing or empty",
			})
		}

		if cmd.MachineID == "" {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "machine_id",
				Message:      "required field is missing or empty",
			})
		}

		// Params is optional - if not provided, it will be nil which is acceptable
		// Commands without parameters don't need a params field

		if cmd.StepNumber < 0 {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "step_number",
				Message:      "must be a non-negative integer",
			})
		}
	}

	return errors
}
