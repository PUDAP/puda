package nats

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

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
		return fmt.Errorf("failed to get machine commands: %w", err)
	}

	var commands map[string]string
	if err := json.Unmarshal(entry.Value(), &commands); err != nil {
		return fmt.Errorf("failed to parse commands JSON: %w", err)
	}

	fmt.Println(commands["commands"])

	return nil
}

// GetSingleMachineStatus retrieves the status of a specific machine from KV store
func GetSingleMachineStatus(nc *natsio.Conn, machineID string) error {
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

	var status map[string]interface{}
	if err := json.Unmarshal(entry.Value(), &status); err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("Failed to parse state JSON for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("failed to parse state JSON: %w", err)
	}

	jsonBytes, err := json.MarshalIndent(status, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal status: %w", err)
	}
	fmt.Println(string(jsonBytes))

	return nil
}

// ListAliveMachines listens to heartbeat messages and returns a list of alive machines
func ListAliveMachines(nc *natsio.Conn) error {
	machineHeartbeats := make(map[string]time.Time)

	subject := "puda.*.tlm.heartbeat"
	sub, err := nc.Subscribe(subject, func(msg *natsio.Msg) {
		parts := strings.Split(msg.Subject, ".")
		if len(parts) >= 2 {
			machineID := parts[1]
			machineHeartbeats[machineID] = time.Now()
		}
	})
	if err != nil {
		return fmt.Errorf("failed to subscribe to heartbeat messages: %w", err)
	}
	defer sub.Unsubscribe()

	// Listen for 3 seconds to catch at least one heartbeat cycle
	time.Sleep(3 * time.Second)

	if len(machineHeartbeats) == 0 {
		fmt.Println("No alive machines found")
		return nil
	}

	fmt.Printf("%-20s %-30s\n", "MACHINE ID", "LAST HEARTBEAT")
	fmt.Println(strings.Repeat("-", 52))

	for machineID, timestamp := range machineHeartbeats {
		fmt.Printf("%-20s %-30s\n", machineID, timestamp.Format(time.RFC3339))
	}

	return nil
}
