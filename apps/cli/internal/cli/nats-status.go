package cli

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/nats"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

// natsStatusCmd is a subcommand of natsCmd that retrieves machine status from NATS Key-Value store
//
// Usage: puda nats status [--machine-id <machine_id>]
var natsStatusCmd = &cobra.Command{
	Use:   "status",
	Short: "Get machine status from NATS Key-Value store or list alive machines",
	Long: `Get the current status of a machine from NATS Key-Value store, or list all alive machines.

If --machine-id is provided, retrieves the status from the NATS JetStream Key-Value bucket.
If --machine-id is not provided, listens to heartbeat messages and returns a list of alive machines.

Requires a .env file in the project root with:
  NATS_SERVERS: Comma-separated list of NATS server URLs

Examples:
  puda nats status --machine-id first
  puda nats status`,
	RunE: getMachineStatus,
}

// Status command flags
var (
	machineID string
)

// init registers flags for the status command
func init() {
	natsStatusCmd.Flags().StringVar(&machineID, "machine-id", "", "Machine ID to retrieve status for (optional - if not provided, lists all alive machines)")
	natsStatusCmd.Flags().StringVar(&natsServers, "nats-servers", "", "Comma-separated NATS server URLs - overrides NATS_SERVERS from .env")
}

// getMachineStatus executes the status command
func getMachineStatus(cmd *cobra.Command, args []string) error {
	// Load from .env file (unless overridden by command line)
	_, _, envNatsServers, err := nats.LoadEnvConfig()
	if err != nil && natsServers == "" {
		// Only error if no command line override provided
		return fmt.Errorf("failed to load environment configuration: %w", err)
	}

	// Use command line args if provided, otherwise use .env values
	finalNatsServers := natsServers
	if finalNatsServers == "" {
		finalNatsServers = envNatsServers
	}

	if finalNatsServers == "" {
		return fmt.Errorf("NATS_SERVERS is required (set in .env or use --nats-servers flag)")
	}

	// Parse NATS servers
	servers := nats.ParseNATSServers(finalNatsServers)

	// Connect to NATS
	nc, err := natsio.Connect(strings.Join(servers, ","), natsio.MaxReconnects(3), natsio.ReconnectWait(2))
	if err != nil {
		return fmt.Errorf("failed to connect to NATS: %w", err)
	}
	defer nc.Close()

	// If machine-id is provided, get status from KV store
	if machineID != "" {
		return getSingleMachineStatus(nc, machineID)
	}

	// Otherwise, listen to heartbeats and return list of alive machines
	return listAliveMachines(nc)
}

// getSingleMachineStatus retrieves the status of a specific machine from KV store
func getSingleMachineStatus(nc *natsio.Conn, machineID string) error {
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}

	// Derive KV bucket name from machine_id (replace dots with dashes)
	kvBucketName := fmt.Sprintf("MACHINE_STATE_%s", strings.ReplaceAll(machineID, ".", "-"))

	// Get the Key-Value store
	kv, err := js.KeyValue(kvBucketName)
	if err != nil {
		// Try to return a JSON error response
		errorResponse := map[string]string{
			"error": fmt.Sprintf("KV bucket not found for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("KV bucket not found: %w", err)
	}

	// Get the machine state
	entry, err := kv.Get(machineID)
	if err != nil {
		// Try to return a JSON error response
		errorResponse := map[string]string{
			"error": fmt.Sprintf("Could not find state for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("failed to get machine state: %w", err)
	}

	// Parse the JSON value
	var status map[string]interface{}
	if err := json.Unmarshal(entry.Value(), &status); err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("Failed to parse state JSON for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("failed to parse state JSON: %w", err)
	}

	// Print result as JSON
	jsonBytes, err := json.MarshalIndent(status, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal status: %w", err)
	}
	fmt.Println(string(jsonBytes))

	return nil
}

// listAliveMachines listens to heartbeat messages and returns a list of alive machines
func listAliveMachines(nc *natsio.Conn) error {
	// Map to store the last heartbeat timestamp for each machine
	machineHeartbeats := make(map[string]time.Time)

	// Subscribe to heartbeat messages using wildcard
	subject := "puda.*.tlm.heartbeat"
	sub, err := nc.Subscribe(subject, func(msg *natsio.Msg) {
		// Parse subject to extract machine_id
		// Format: puda.{machine_id}.tlm.heartbeat
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

	// Listen for 3 seconds to collect heartbeats
	// This should catch at least one heartbeat cycle since machines send every second
	time.Sleep(3 * time.Second)

	// Convert to list format
	var machines []nats.MachineHeartbeat
	for machineID, timestamp := range machineHeartbeats {
		machines = append(machines, nats.MachineHeartbeat{
			MachineID: machineID,
			Timestamp: timestamp.Format(time.RFC3339),
		})
	}

	// Print result as JSON
	jsonBytes, err := json.MarshalIndent(machines, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal machine list: %w", err)
	}
	fmt.Println(string(jsonBytes))

	return nil
}
