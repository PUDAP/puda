package nats

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	natsio "github.com/nats-io/nats.go"
)

// DiscoverMachines subscribes to puda.*.tlm.heartbeat for the given duration
// and returns the unique machine IDs that were seen.
func DiscoverMachines(nc *natsio.Conn, timeout time.Duration) ([]string, error) {
	seen := make(map[string]struct{})

	sub, err := nc.Subscribe("puda.*.tlm.heartbeat", func(msg *natsio.Msg) {
		parts := strings.Split(msg.Subject, ".")
		if len(parts) >= 2 {
			seen[parts[1]] = struct{}{}
		}
	})
	if err != nil {
		return nil, fmt.Errorf("failed to subscribe to heartbeat: %w", err)
	}
	defer sub.Unsubscribe()

	time.Sleep(timeout)

	machines := make([]string, 0, len(seen))
	for id := range seen {
		machines = append(machines, id)
	}
	return machines, nil
}

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
