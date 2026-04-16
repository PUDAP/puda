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
	"syscall"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
)

// completeAllMachines sends COMPLETE commands to all started machines
func completeAllMachines(js nats.JetStreamContext, dispatcher *ResponseDispatcher, startedMachines map[string]bool, runID, userID, username string, timeoutSeconds int, stepNumber int, store *db.Store) {
	log.Printf("Completing runs on all machines")
	for machineID := range startedMachines {
		_, completeErr := SendCompleteCommand(js, dispatcher, machineID, runID, userID, username, timeoutSeconds, stepNumber, store)
		if completeErr != nil {
			log.Printf("Failed to complete run for machine %s: %v", machineID, completeErr)
		}
	}
}

// SendQueueCommands sends a batch of queued commands sequentially
func SendQueueCommands(js nats.JetStreamContext, dispatcher *ResponseDispatcher, requests []puda.CommandRequest, runID, userID, username string, store *db.Store) error {
	const defaultTimeout = 30 // for immediate commands which should complete pretty much instantly

	if len(requests) == 0 {
		return fmt.Errorf("no commands to send")
	}

	completeStepNumber := len(requests) + 1
	if lastStepNumber := requests[len(requests)-1].StepNumber; lastStepNumber > 0 {
		completeStepNumber = lastStepNumber + 1
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
		completeAllMachines(js, dispatcher, startedMachines, runID, userID, username, defaultTimeout, completeStepNumber, store)
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

		response, err := SendStartCommand(js, dispatcher, machineID, runID, userID, username, defaultTimeout, store)
		if err != nil {
			completeAllMachines(js, dispatcher, startedMachines, runID, userID, username, defaultTimeout, completeStepNumber, store)
			return fmt.Errorf("START command failed for machine %s: %w", machineID, err)
		}
		if response.Response != nil && response.Response.Status == puda.StatusError {
			completeAllMachines(js, dispatcher, startedMachines, runID, userID, username, defaultTimeout, completeStepNumber, store)
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

		response, err := SendQueueCommand(js, dispatcher, request, runID, userID, username, store)
		if err != nil {
			// Complete all started runs
			completeAllMachines(js, dispatcher, startedMachines, runID, userID, username, defaultTimeout, completeStepNumber, store)
			return fmt.Errorf("command %d/%d failed or timed out: %w", idx+1, len(requests), err)
		}

		if response.Response == nil {
			// Complete all started runs
			completeAllMachines(js, dispatcher, startedMachines, runID, userID, username, defaultTimeout, completeStepNumber, store)
			return fmt.Errorf("command %d/%d returned response with no response data", idx+1, len(requests))
		}

		if response.Response.Status == puda.StatusError {
			// Complete all started runs
			completeAllMachines(js, dispatcher, startedMachines, runID, userID, username, defaultTimeout, completeStepNumber, store)
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
	completeAllMachines(js, dispatcher, machineIDs, runID, userID, username, defaultTimeout, completeStepNumber, store)

	return nil
}

// RunProtocol executes a puda protocol via NATS
func RunProtocol(protocolFile *puda.ProtocolFile, natsServers string, startStep int) error {
	// Initialize database connection (optional - if it fails, database operations will be skipped gracefully)
	store, err := db.Connect()
	if err != nil {
		log.Printf("Warning: failed to connect to database for command logging: %v", err)
		store = nil
	} else {
		defer store.Disconnect()
	}

	// if natsServers is not provided, use the active profile from the global config
	finalNatsServers := natsServers
	if finalNatsServers == "" {
		globalCfg, err := puda.LoadGlobalConfig()
		if err != nil {
			return fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
		}
		finalNatsServers = globalCfg.ActiveProfileNATSServers()
	}

	// user_id and username must be provided in the protocol file
	if protocolFile.UserID == "" {
		return fmt.Errorf("user_id is required in the protocol file")
	}
	if protocolFile.Username == "" {
		return fmt.Errorf("username is required in the protocol file")
	}

	finalUserID := protocolFile.UserID
	finalUsername := protocolFile.Username

	// Insert run into database
	runID := uuid.New().String()
	if store != nil {
		if err := store.InsertRun(runID, &protocolFile.ProtocolID); err != nil {
			// Log warning but don't fail - database logging is optional
			log.Printf("Warning: failed to insert run into database: %v", err)
		}
	}

	// Set up logging to both console and file
	projectRoot := "."
	if projCfg, err := puda.LoadProjectConfig(); err == nil && projCfg.ProjectRoot != "" {
		projectRoot = projCfg.ProjectRoot
	}
	logsDir := filepath.Join(projectRoot, "logs")
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

	log.Printf("Protocol created by %s (%s) at %s", finalUsername, finalUserID, protocolFile.Timestamp)
	log.Printf("Description: %s", protocolFile.Description)

	log.Printf("Run ID: %s", runID)
	log.Printf("Ran by: %s (%s)", finalUsername, finalUserID)
	log.Printf("Logging output to: %s", logFilePath)

	// Parse NATS servers
	log.Printf("Connecting to NATS servers: %v", finalNatsServers)

	// Connect to NATS
	nc, err := nats.Connect(finalNatsServers, nats.MaxReconnects(3), nats.ReconnectWait(2*time.Second))
	if err != nil {
		return fmt.Errorf("failed to connect to NATS: %w", err)
	}
	defer nc.Close()

	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}

	log.Printf("Connected to NATS servers")

	// Create response dispatcher with a single long-lived subscription per user
	dispatcher := NewResponseDispatcher(js, finalUserID)
	if err := dispatcher.Start(); err != nil {
		return fmt.Errorf("failed to start response dispatcher: %w", err)
	}
	defer dispatcher.Close()

	// Extract commands from protocol file
	commands := protocolFile.Commands
	if len(commands) == 0 {
		return fmt.Errorf("protocol contains no commands")
	}
	if startStep < 1 || startStep > len(commands) {
		return fmt.Errorf("start step must be between 1 and %d", len(commands))
	}
	if startStep > 1 {
		log.Printf("Starting protocol from step %d", startStep)
		commands = commands[startStep-1:]
	}
	log.Printf("Loaded %d commands from protocol, executing %d command(s) starting at step %d\n", len(protocolFile.Commands), len(commands), startStep)

	// Send batch commands
	if err := SendQueueCommands(js, dispatcher, commands, runID, finalUserID, finalUsername, store); err != nil {
		log.Printf("Batch commands failed: %v", err)
		return err
	}

	log.Printf("Batch commands completed successfully!")
	return nil
}
