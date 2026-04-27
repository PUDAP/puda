package puda

import (
	"encoding/json"
	"fmt"
	"os"
)

// ValidationError represents a validation error
type ValidationError struct {
	CommandIndex int
	Field        string
	Message      string
}

// LoadProtocol loads a protocol file (JSON with commands and metadata) from disk
// Returns the raw JSON bytes of the ProtocolFile
func LoadProtocol(filePath string) ([]byte, error) {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to read commands file: %w", err)
	}

	// Validate that it's valid JSON and has the expected structure
	var protocolFile ProtocolFile
	if err := json.Unmarshal(data, &protocolFile); err != nil {
		return nil, fmt.Errorf("failed to parse JSON: expected an object with 'commands' field: %w", err)
	}

	if len(protocolFile.Commands) == 0 {
		return nil, fmt.Errorf("commands array is empty or missing")
	}

	// Initialize nil params to empty maps
	for i := range protocolFile.Commands {
		if protocolFile.Commands[i].Params == nil {
			protocolFile.Commands[i].Params = make(map[string]interface{})
		}
	}

	// Re-marshal to ensure consistent JSON format
	jsonBytes, err := json.Marshal(protocolFile)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal protocol file: %w", err)
	}

	return jsonBytes, nil
}

// ValidateCommandStructure validates the structure of commands
func ValidateCommandStructure(commands []CommandRequest) []ValidationError {
	var errors []ValidationError
	stepMachinePairs := make(map[string]int)
	previousStepNumber := -1

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
		} else if previousStepNumber > cmd.StepNumber {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "step_number",
				Message:      fmt.Sprintf("must not decrease from previous step %d", previousStepNumber),
			})
		}
		if cmd.StepNumber >= 0 {
			previousStepNumber = cmd.StepNumber
		}

		if cmd.MachineID != "" && cmd.StepNumber >= 0 {
			stepMachineKey := fmt.Sprintf("%s:%d", cmd.MachineID, cmd.StepNumber)
			if previousIndex, ok := stepMachinePairs[stepMachineKey]; ok {
				errors = append(errors, ValidationError{
					CommandIndex: i,
					Field:        "step_number",
					Message:      fmt.Sprintf("duplicates command #%d for machine %s at step %d", previousIndex+1, cmd.MachineID, cmd.StepNumber),
				})
			} else {
				stepMachinePairs[stepMachineKey] = i
			}
		}
	}

	return errors
}

// ValidateProtocol validates a protocol file and returns validation errors
// It validates the command structure
// Returns validation errors and an error (non-nil if validation fails)
func ValidateProtocol(protocolFile *ProtocolFile) ([]ValidationError, error) {
	// Validate commands
	validationErrors := ValidateCommandStructure(protocolFile.Commands)

	// If there are validation errors, return them as an error
	if len(validationErrors) > 0 {
		return validationErrors, fmt.Errorf("protocol validation failed: %v", validationErrors)
	}

	return validationErrors, nil
}
