package nats

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
)

// completeAllMachines sends COMPLETE commands to all started machines
func completeAllMachines(nc *nats.Conn, js nats.JetStreamContext, startedMachines map[string]bool, runID, userID, username string, timeoutSeconds int) {
	log.Printf("Completing runs on all machines")
	for machineID := range startedMachines {
		_, completeErr := SendCompleteCommand(nc, js, machineID, runID, userID, username, timeoutSeconds)
		if completeErr != nil {
			log.Printf("Failed to complete run for machine %s: %v", machineID, completeErr)
		}
	}
}

// SendQueueCommands sends a batch of queued commands sequentially
func SendQueueCommands(nc *nats.Conn, js nats.JetStreamContext, requests []puda.CommandRequest, runID, userID, username string, timeoutSeconds int) error {
	if len(requests) == 0 {
		return fmt.Errorf("no commands to send")
	}

	// Collect unique machine IDs
	machineIDs := make(map[string]bool)
	for _, req := range requests {
		if req.MachineID == "" {
			return fmt.Errorf("command missing machine_id: %+v", req)
		}
		machineIDs[req.MachineID] = true
	}

	machineIDList := make([]string, 0, len(machineIDs))
	for id := range machineIDs {
		machineIDList = append(machineIDList, id)
	}

	log.Printf("Sending %d queue commands sequentially to machines: %v, run_id=%s", len(requests), machineIDList, runID)

	// Set up signal handling for graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	// Track started machines for cleanup
	startedMachines := make(map[string]bool)

	// Goroutine to handle signals
	interrupted := make(chan bool, 1)
	go func() {
		<-sigChan
		log.Printf("Interrupt signal received, sending COMPLETE commands to all machines...")
		completeAllMachines(nc, js, startedMachines, runID, userID, username, timeoutSeconds)
		interrupted <- true
		cancel()
	}()

	// Send START commands to all machines
	log.Printf("Sending START commands to all machines: %v", machineIDList)
	for _, machineID := range machineIDList {
		// Check if interrupted
		select {
		case <-interrupted:
			return fmt.Errorf("interrupted before starting machines")
		case <-ctx.Done():
			return fmt.Errorf("interrupted before starting machines")
		default:
		}

		response, err := SendStartCommand(nc, js, machineID, runID, userID, username, timeoutSeconds)
		if err != nil {
			completeAllMachines(nc, js, startedMachines, runID, userID, username, timeoutSeconds)
			return fmt.Errorf("START command failed for machine %s: %w", machineID, err)
		}
		if response.Response != nil && response.Response.Status == puda.StatusError {
			completeAllMachines(nc, js, startedMachines, runID, userID, username, timeoutSeconds)
			return fmt.Errorf("START command failed for machine %s: %s", machineID, GetResponseMessage(response))
		}
		startedMachines[machineID] = true
	}

	// Send commands sequentially
	for idx, request := range requests {
		// Check if interrupted
		select {
		case <-interrupted:
			return fmt.Errorf("interrupted during command execution")
		case <-ctx.Done():
			return fmt.Errorf("interrupted during command execution")
		default:
		}

		log.Printf("Sending command %d/%d: %s (step %d) to machine %s", idx+1, len(requests), request.Name, request.StepNumber, request.MachineID)

		response, err := SendQueueCommand(nc, js, request, runID, userID, username)
		if err != nil {
			// Complete all started runs
			completeAllMachines(nc, js, startedMachines, runID, userID, username, timeoutSeconds)
			return fmt.Errorf("command %d/%d failed or timed out: %w", idx+1, len(requests), err)
		}

		if response.Response == nil {
			// Complete all started runs
			completeAllMachines(nc, js, startedMachines, runID, userID, username, timeoutSeconds)
			return fmt.Errorf("command %d/%d returned response with no response data", idx+1, len(requests))
		}

		if response.Response.Status == puda.StatusError {
			// Complete all started runs
			completeAllMachines(nc, js, startedMachines, runID, userID, username, timeoutSeconds)
			return fmt.Errorf("command %d/%d failed with error: %s", idx+1, len(requests), GetResponseMessage(response))
		}

		log.Printf("Command %d/%d succeeded: %s (step %d)", idx+1, len(requests), request.Name, request.StepNumber)

		// Log response details
		responseJSON, err := json.MarshalIndent(response, "", "  ")
		if err != nil {
			log.Printf("Response (unable to marshal): %+v", response)
		} else {
			log.Printf("Response: %s", string(responseJSON))
		}
	}

	log.Printf("All %d commands completed successfully", len(requests))

	// Send COMPLETE commands to all machines
	log.Printf("Sending COMPLETE commands to all machines: %v", machineIDList)
	completeAllMachines(nc, js, machineIDs, runID, userID, username, timeoutSeconds)

	return nil
}

// SendProtocol executes a puda protocol via NATS
func SendProtocol(protocolJSON []byte, timeout int, natsServers string) error {
	// Load NATS_SERVERS from .env file (unless overridden by command line)
	_, _, envNatsServers, err := LoadEnvConfig()
	if err != nil && natsServers == "" {
		// Only error if .env is missing AND no flag provided
		return fmt.Errorf("NATS_SERVERS is required (set in .env or use --nats-servers flag): %w", err)
	}

	finalNatsServers := natsServers
	if finalNatsServers == "" {
		finalNatsServers = envNatsServers
	}

	if finalNatsServers == "" {
		return fmt.Errorf("NATS_SERVERS is required (set in .env or use --nats-servers flag)")
	}

	// Parse protocol JSON
	var protocolFile puda.ProtocolFile
	if err := json.Unmarshal(protocolJSON, &protocolFile); err != nil {
		return fmt.Errorf("failed to parse protocol JSON: %w", err)
	}

	commands := protocolFile.Commands
	log.Printf("Loaded %d commands from protocol", len(commands))

	// user_id and username must be provided in the JSON file
	if protocolFile.UserID == "" {
		return fmt.Errorf("user_id is required in the JSON file")
	}
	if protocolFile.Username == "" {
		return fmt.Errorf("username is required in the JSON file")
	}

	finalUserID := protocolFile.UserID
	finalUsername := protocolFile.Username

	log.Printf("Using user_id from protocol: %s", finalUserID)
	log.Printf("Using username from protocol: %s", finalUsername)
	if protocolFile.Description != "" {
		log.Printf("Description: %s", protocolFile.Description)
	}

	// Generate unique run_id
	runID := uuid.New().String()

	// Set up logging to both console and file
	logsDir := "./logs"
	if err := os.MkdirAll(logsDir, 0755); err != nil {
		return fmt.Errorf("failed to create logs directory: %w", err)
	}

	logFilePath := filepath.Join(logsDir, fmt.Sprintf("%s.log", runID))
	logFile, err := os.OpenFile(logFilePath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if err != nil {
		return fmt.Errorf("failed to open log file: %w", err)
	}
	defer logFile.Close()

	// Create a multi-writer that writes to both stdout and the log file
	multiWriter := io.MultiWriter(os.Stdout, logFile)
	log.SetOutput(multiWriter)
	defer log.SetOutput(os.Stderr) // Restore default log output (stderr) when done

	log.Printf("Run ID: %s", runID)
	log.Printf("User: %s (%s)", finalUsername, finalUserID)
	log.Printf("Description: %s", protocolFile.Description)
	log.Printf("Logging output to: %s", logFilePath)

	// Parse NATS servers
	servers := ParseNATSServers(finalNatsServers)
	log.Printf("NATS servers: %v", servers)

	// Connect to NATS
	nc, err := nats.Connect(strings.Join(servers, ","), nats.MaxReconnects(3), nats.ReconnectWait(2*time.Second))
	if err != nil {
		return fmt.Errorf("failed to connect to NATS: %w", err)
	}
	defer nc.Close()

	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}

	log.Printf("Connected to NATS, sending batch commands...")

	// Send batch commands
	if err := SendQueueCommands(nc, js, commands, runID, finalUserID, finalUsername, timeout); err != nil {
		log.Printf("Batch commands failed: %v", err)
		return err
	}

	log.Printf("Batch commands completed successfully!")
	return nil
}
