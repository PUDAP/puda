package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/spf13/cobra"
)

// natsCommandValidateCmd is a subcommand of natsCommandCmd that validates a commands JSON file
//
// Usage: puda nats command validate --file <path>
var natsCommandValidateCmd = &cobra.Command{
	Use:   "validate",
	Short: "Validate a commands JSON file",
	Long: `Validate a commands JSON file to ensure it has the correct structure and required fields.

Checks:
  - Valid JSON format
  - Array of command objects
  - Each command has required fields: name, machine_id, params, step_number

Example:
  puda nats command validate --file commands.json`,
	RunE: validateCommands,
}

// Command validate flags
var (
	validateFile string
)

// init registers flags for the validate command
func init() {
	natsCommandValidateCmd.Flags().StringVarP(&validateFile, "file", "f", "", "Path to JSON file containing array of commands (required)")
	natsCommandValidateCmd.MarkFlagRequired("file")
}

// ValidationError represents a validation error
type ValidationError struct {
	CommandIndex int
	Field        string
	Message      string
}

// validateCommands executes the validate command
func validateCommands(cmd *cobra.Command, args []string) error {
	// Load commands from file - this validates the JSON structure matches CommandRequest
	commands, err := nats.LoadCommands(validateFile)
	if err != nil {
		return fmt.Errorf("validation failed: %w", err)
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
func validateCommandStructure(commands []nats.CommandRequest) []ValidationError {
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

		if cmd.Params == nil {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "params",
				Message:      "required field is missing (must be an object)",
			})
		}

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
