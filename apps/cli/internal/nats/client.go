package nats

import (
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/nats-io/nats.go"
)

// SendImmediateCommand sends an immediate command to a machine
func SendImmediateCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	subject := fmt.Sprintf("puda.%s.cmd.immediate", request.MachineID)
	payload := BuildCommandPayload(request, request.MachineID, runID, userID, username)

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command payload: %w", err)
	}

	responseCh := dispatcher.Register(runID, request.StepNumber, request.MachineID)
	defer dispatcher.Unregister(runID, request.StepNumber, request.MachineID)

	// Publish command
	_, err = js.Publish(subject, payloadJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to publish command: %w", err)
	}

	// Wait for response with timeout
	timeout := time.Duration(timeoutSeconds) * time.Second
	select {
	case response := <-responseCh:
		if store != nil && response.Response != nil {
			if err := store.InsertCommandLog(response, "immediate"); err != nil {
				log.Printf("Failed to insert command log: %v", err)
			}
		}
		return response, nil
	case <-time.After(timeout):
		return nil, fmt.Errorf("timeout waiting for response after %d seconds", timeoutSeconds)
	}
}

// SendQueueCommand sends a queued command to a machine
func SendQueueCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, request puda.CommandRequest, runID, userID, username string, store *db.Store) (*puda.NATSMessage, error) {
	subject := fmt.Sprintf("puda.%s.cmd.queue", request.MachineID)
	payload := BuildCommandPayload(request, request.MachineID, runID, userID, username)

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command payload: %w", err)
	}

	responseCh := dispatcher.Register(runID, request.StepNumber, request.MachineID)
	defer dispatcher.Unregister(runID, request.StepNumber, request.MachineID)

	// Publish command with ack wait long enough for busy streams (default is 5s), retry up to 3 times
	const publishAckWait = 10 * time.Second
	const maxPublishRetries = 3
	for attempt := 1; attempt <= maxPublishRetries; attempt++ {
		_, err = js.Publish(subject, payloadJSON, nats.AckWait(publishAckWait))
		if err == nil {
			break
		}
		if attempt < maxPublishRetries {
			log.Printf("Publish attempt %d/%d failed: %v; retrying...", attempt, maxPublishRetries, err)
			time.Sleep(time.Second * time.Duration(attempt))
		} else {
			return nil, fmt.Errorf("failed to publish command after %d attempts: %w", maxPublishRetries, err)
		}
	}

	// Wait for response (no timeout)
	response := <-responseCh
	if store != nil && response.Response != nil {
		if err := store.InsertCommandLog(response, "queue"); err != nil {
			log.Printf("Failed to insert command log: %v", err)
		}
	}
	return response, nil
}

// SendStartCommand sends a START command to a machine
func SendStartCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandStart,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(js, dispatcher, request, runID, userID, username, timeoutSeconds, store)
}

// SendCompleteCommand sends a COMPLETE command to a machine
func SendCompleteCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, machineID, runID, userID, username string, timeoutSeconds int, stepNumber int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandComplete,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: stepNumber,
		Version:    "1.0",
	}
	return SendImmediateCommand(js, dispatcher, request, runID, userID, username, timeoutSeconds, store)
}

// SendResetCommand sends a RESET immediate command to a machine
func SendResetCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandReset,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(js, dispatcher, request, runID, userID, username, timeoutSeconds, store)
}
