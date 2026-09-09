package puda

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sort"
	"time"
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
		waitCommand := IsWaitCommand(cmd)

		// Validate required fields
		if cmd.Name == "" {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "name",
				Message:      "required field is missing or empty",
			})
		}

		if !waitCommand && cmd.MachineID == "" {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "machine_id",
				Message:      "required field is missing or empty",
			})
		}

		if waitCommand {
			errors = append(errors, waitCommandErrors(i, cmd)...)
		}

		// Params is optional - if not provided, it will be nil which is acceptable
		// Commands without parameters don't need a params field

		if i == 0 && cmd.StepNumber != 1 {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "step_number",
				Message:      "must start at 1",
			})
		} else if cmd.StepNumber < 1 {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "step_number",
				Message:      "must be an integer greater than or equal to 1",
			})
		} else if previousStepNumber > cmd.StepNumber {
			errors = append(errors, ValidationError{
				CommandIndex: i,
				Field:        "step_number",
				Message:      fmt.Sprintf("must not decrease from previous step %d", previousStepNumber),
			})
		}
		if cmd.StepNumber >= 1 {
			previousStepNumber = cmd.StepNumber
		}

		if cmd.MachineID != "" && cmd.StepNumber >= 1 {
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

// IsWaitCommand reports whether the command is the CLI-handled wait builtin.
func IsWaitCommand(command CommandRequest) bool {
	return command.Name == WaitCommandName
}

func waitCommandErrors(commandIndex int, command CommandRequest) []ValidationError {
	errors := make([]ValidationError, 0)
	if len(command.Kwargs) > 0 {
		errors = append(errors, ValidationError{
			CommandIndex: commandIndex,
			Field:        "kwargs",
			Message:      "wait does not accept kwargs",
		})
	}

	params := command.Params
	if params == nil {
		params = map[string]interface{}{}
	}
	names := make([]string, 0, len(params))
	for name := range params {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		if name != WaitParamSeconds {
			errors = append(errors, ValidationError{
				CommandIndex: commandIndex,
				Field:        "params." + name,
				Message:      fmt.Sprintf("wait does not accept parameter %s", name),
			})
		}
	}

	if _, err := ParseWaitDuration(params); err != nil {
		errors = append(errors, ValidationError{
			CommandIndex: commandIndex,
			Field:        "params." + WaitParamSeconds,
			Message:      err.Error(),
		})
	}
	return errors
}

// ParseWaitDuration reads params.seconds as a duration. Values may be fractional.
func ParseWaitDuration(params map[string]interface{}) (time.Duration, error) {
	if params == nil {
		return 0, fmt.Errorf("required parameter %s is missing", WaitParamSeconds)
	}
	raw, ok := params[WaitParamSeconds]
	if !ok {
		return 0, fmt.Errorf("required parameter %s is missing", WaitParamSeconds)
	}
	seconds, ok := waitSecondsValue(raw)
	if !ok {
		return 0, fmt.Errorf("parameter %s must be a number", WaitParamSeconds)
	}
	if math.IsNaN(seconds) || math.IsInf(seconds, 0) {
		return 0, fmt.Errorf("parameter %s must be a finite number", WaitParamSeconds)
	}
	if seconds < 0 {
		return 0, fmt.Errorf("parameter %s must be greater than or equal to 0", WaitParamSeconds)
	}
	maxSeconds := float64(math.MaxInt64 / int64(time.Second))
	if seconds > maxSeconds {
		return 0, fmt.Errorf("parameter %s is too large", WaitParamSeconds)
	}
	return time.Duration(seconds * float64(time.Second)), nil
}

func waitSecondsValue(value interface{}) (float64, bool) {
	switch typed := value.(type) {
	case float64:
		return typed, true
	case float32:
		return float64(typed), true
	case int:
		return float64(typed), true
	case int64:
		return float64(typed), true
	case json.Number:
		seconds, err := typed.Float64()
		return seconds, err == nil
	default:
		return 0, false
	}
}
