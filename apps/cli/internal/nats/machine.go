package nats

import (
	"encoding/json"
	"fmt"
	"strings"

	natsio "github.com/nats-io/nats.go"
)

// GetMachineCommands retrieves the commands of a specific machine from KV store
func GetMachineCommands(nc *natsio.Conn, machineID string) error {
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}
	kvBucketName := fmt.Sprintf("MACHINE_COMMANDS_%s", strings.ReplaceAll(machineID, ".", "-"))
	kv, err := js.KeyValue(kvBucketName)
	if err != nil {
		return fmt.Errorf("failed to get KV bucket: %w", err)
	}

	entry, err := kv.Get(machineID)
	if err != nil {
		return fmt.Errorf("failed to get %s commands: %w", machineID, err)
	}

	var commands map[string]string
	if err := json.Unmarshal(entry.Value(), &commands); err != nil {
		return fmt.Errorf("failed to parse commands JSON: %w", err)
	}

	fmt.Println(commands["commands"])

	return nil
}

// GetSingleMachineState retrieves the state of a specific machine from KV store
func GetSingleMachineState(nc *natsio.Conn, machineID string) error {
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}

	kvBucketName := fmt.Sprintf("MACHINE_STATE_%s", strings.ReplaceAll(machineID, ".", "-"))

	kv, err := js.KeyValue(kvBucketName)
	if err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("KV bucket not found for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("KV bucket not found: %w", err)
	}

	entry, err := kv.Get(machineID)
	if err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("Could not find state for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("failed to get machine state: %w", err)
	}

	var state map[string]interface{}
	if err := json.Unmarshal(entry.Value(), &state); err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("Failed to parse state JSON for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("failed to parse state JSON: %w", err)
	}

	jsonBytes, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}
	fmt.Println(string(jsonBytes))

	return nil
}

