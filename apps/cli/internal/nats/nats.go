package nats

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
)

// SendStartCommand sends a START command to a machine
func SendStartCommand(nc *nats.Conn, js nats.JetStreamContext, machineID, runID, userID, username string, timeoutSeconds int) (*NATSMessage, error) {
	request := CommandRequest{
		Name:       "start",
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(nc, js, request, runID, userID, username, timeoutSeconds)
}

// SendCompleteCommand sends a COMPLETE command to a machine
func SendCompleteCommand(nc *nats.Conn, js nats.JetStreamContext, machineID, runID, userID, username string, timeoutSeconds int) (*NATSMessage, error) {
	request := CommandRequest{
		Name:       "complete",
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(nc, js, request, runID, userID, username, timeoutSeconds)
}

// SendImmediateCommand sends an immediate command to a machine
func SendImmediateCommand(nc *nats.Conn, js nats.JetStreamContext, request CommandRequest, runID, userID, username string, timeoutSeconds int) (*NATSMessage, error) {
	subject := fmt.Sprintf("puda.%s.cmd.immediate", request.MachineID)
	payload := BuildCommandPayload(request, request.MachineID, runID, userID, username)

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command payload: %w", err)
	}

	// Subscribe to response stream before publishing
	responseSubject := fmt.Sprintf("puda.%s.cmd.response.immediate", request.MachineID)
	responseCh := make(chan *NATSMessage, 1)

	// Create ephemeral consumer for response stream
	sub, err := js.Subscribe(responseSubject, func(msg *nats.Msg) {
		var response NATSMessage
		if err := json.Unmarshal(msg.Data, &response); err != nil {
			log.Printf("Failed to unmarshal response: %v", err)
			msg.Ack()
			return
		}

		// Check if this response matches our request (run_id and step_number)
		if response.Header.RunID != nil && *response.Header.RunID == runID {
			if response.Command != nil && response.Command.StepNumber == request.StepNumber {
				select {
				case responseCh <- &response:
				default:
				}
				msg.Ack()
				return
			}
		}
		// Not our response, acknowledge to remove from queue
		msg.Ack()
	}, nats.Durable(fmt.Sprintf("batch-immediate-%s-%d", runID, request.StepNumber)))
	if err != nil {
		return nil, fmt.Errorf("failed to subscribe to response: %w", err)
	}
	defer sub.Unsubscribe()

	// Publish command
	_, err = js.Publish(subject, payloadJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to publish command: %w", err)
	}

	// Wait for response with timeout
	timeout := time.Duration(timeoutSeconds) * time.Second
	select {
	case response := <-responseCh:
		return response, nil
	case <-time.After(timeout):
		return nil, fmt.Errorf("timeout waiting for response after %d seconds", timeoutSeconds)
	}
}

// SendQueueCommand sends a queued command to a machine
func SendQueueCommand(nc *nats.Conn, js nats.JetStreamContext, request CommandRequest, runID, userID, username string, timeoutSeconds int) (*NATSMessage, error) {
	subject := fmt.Sprintf("puda.%s.cmd.queue", request.MachineID)
	payload := BuildCommandPayload(request, request.MachineID, runID, userID, username)

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command payload: %w", err)
	}

	// Subscribe to response stream before publishing
	responseSubject := fmt.Sprintf("puda.%s.cmd.response.queue", request.MachineID)
	responseCh := make(chan *NATSMessage, 1)

	// Create ephemeral consumer for response stream
	sub, err := js.Subscribe(responseSubject, func(msg *nats.Msg) {
		var response NATSMessage
		if err := json.Unmarshal(msg.Data, &response); err != nil {
			log.Printf("Failed to unmarshal response: %v", err)
			msg.Ack()
			return
		}

		// Check if this response matches our request (run_id and step_number)
		if response.Header.RunID != nil && *response.Header.RunID == runID {
			if response.Command != nil && response.Command.StepNumber == request.StepNumber {
				select {
				case responseCh <- &response:
				default:
				}
				msg.Ack()
				return
			}
		}
		// Not our response, acknowledge to remove from queue
		msg.Ack()
	}, nats.Durable(fmt.Sprintf("batch-queue-%s-%d", runID, request.StepNumber)))
	if err != nil {
		return nil, fmt.Errorf("failed to subscribe to response: %w", err)
	}
	defer sub.Unsubscribe()

	// Publish command
	_, err = js.Publish(subject, payloadJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to publish command: %w", err)
	}

	// Wait for response with timeout
	timeout := time.Duration(timeoutSeconds) * time.Second
	select {
	case response := <-responseCh:
		return response, nil
	case <-time.After(timeout):
		return nil, fmt.Errorf("timeout waiting for response after %d seconds", timeoutSeconds)
	}
}

// SendQueueCommands sends a batch of queued commands sequentially
func SendQueueCommands(nc *nats.Conn, js nats.JetStreamContext, requests []CommandRequest, runID, userID, username string, timeoutSeconds int) error {
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

	// Send START commands to all machines
	log.Printf("Sending START commands to all machines: %v", machineIDList)
	startedMachines := make(map[string]bool)
	for _, machineID := range machineIDList {
		response, err := SendStartCommand(nc, js, machineID, runID, userID, username, timeoutSeconds)
		if err != nil {
			return fmt.Errorf("START command failed for machine %s: %w", machineID, err)
		}
		if response.Response != nil && response.Response.Status == StatusError {
			return fmt.Errorf("START command failed for machine %s: %s", machineID, GetResponseMessage(response))
		}
		startedMachines[machineID] = true
	}

	// Send commands sequentially
	for idx, request := range requests {
		log.Printf("Sending command %d/%d: %s (step %d) to machine %s", idx+1, len(requests), request.Name, request.StepNumber, request.MachineID)

		response, err := SendQueueCommand(nc, js, request, runID, userID, username, timeoutSeconds)
		if err != nil {
			// Complete all started runs
			log.Printf("Completing runs on all machines due to error")
			for machineID := range startedMachines {
				_, completeErr := SendCompleteCommand(nc, js, machineID, runID, userID, username, timeoutSeconds)
				if completeErr != nil {
					log.Printf("Failed to complete run for machine %s: %v", machineID, completeErr)
				}
			}
			return fmt.Errorf("command %d/%d failed or timed out: %w", idx+1, len(requests), err)
		}

		if response.Response == nil {
			// Complete all started runs
			log.Printf("Completing runs on all machines due to error")
			for machineID := range startedMachines {
				_, completeErr := SendCompleteCommand(nc, js, machineID, runID, userID, username, timeoutSeconds)
				if completeErr != nil {
					log.Printf("Failed to complete run for machine %s: %v", machineID, completeErr)
				}
			}
			return fmt.Errorf("command %d/%d returned response with no response data", idx+1, len(requests))
		}

		if response.Response.Status == StatusError {
			// Complete all started runs
			log.Printf("Completing runs on all machines due to error")
			for machineID := range startedMachines {
				_, completeErr := SendCompleteCommand(nc, js, machineID, runID, userID, username, timeoutSeconds)
				if completeErr != nil {
					log.Printf("Failed to complete run for machine %s: %v", machineID, completeErr)
				}
			}
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
	for _, machineID := range machineIDList {
		_, err := SendCompleteCommand(nc, js, machineID, runID, userID, username, timeoutSeconds)
		if err != nil {
			log.Printf("Failed to complete run for machine %s: %v", machineID, err)
		}
	}

	return nil
}

// RunBatchCommands executes a batch of commands via NATS
func RunBatchCommands(commandsFile string, timeout int, userID, username, natsServers string) error {
	// Load from .env file (unless overridden by command line)
	envUserID, envUsername, envNatsServers, err := LoadEnvConfig()
	if err != nil {
		return fmt.Errorf("failed to load environment configuration: %w", err)
	}

	// Use command line args if provided, otherwise use .env values
	finalUserID := userID
	if finalUserID == "" {
		finalUserID = envUserID
	}
	finalUsername := username
	if finalUsername == "" {
		finalUsername = envUsername
	}
	finalNatsServers := natsServers
	if finalNatsServers == "" {
		finalNatsServers = envNatsServers
	}

	if finalUserID == "" {
		return fmt.Errorf("USER_ID is required (set in .env or use --user-id flag)")
	}
	if finalUsername == "" {
		return fmt.Errorf("USERNAME is required (set in .env or use --username flag)")
	}
	if finalNatsServers == "" {
		return fmt.Errorf("NATS_SERVERS is required (set in .env or use --nats-servers flag)")
	}

	// Load commands from JSON file
	commands, err := LoadCommands(commandsFile)
	if err != nil {
		return fmt.Errorf("failed to load commands: %w", err)
	}

	log.Printf("Loaded %d commands from file", len(commands))

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
	log.Printf("Logging output to: %s", logFilePath)
	log.Printf("User: %s (%s)", finalUsername, finalUserID)

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
