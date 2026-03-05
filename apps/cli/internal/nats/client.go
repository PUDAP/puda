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
func SendImmediateCommand(nc *nats.Conn, js nats.JetStreamContext, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	subject := fmt.Sprintf("puda.%s.cmd.immediate", request.MachineID)
	payload := BuildCommandPayload(request, request.MachineID, runID, userID, username)

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command payload: %w", err)
	}

	// Subscribe to response stream before publishing
	responseSubject := fmt.Sprintf("puda.%s.cmd.response.immediate", request.MachineID)
	responseCh := make(chan *puda.NATSMessage, 1)

	// Create ephemeral consumer for response stream
	sub, err := js.Subscribe(responseSubject, func(msg *nats.Msg) {
		var response puda.NATSMessage
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
		// Insert into database if response exists and store is available
		if store != nil && response.Response != nil {
			if err := store.InsertCommandLog(response, "immediate"); err != nil {
				log.Printf("Failed to insert command log: %v", err)
				// Don't fail the command if logging fails
			}
		}
		return response, nil
	case <-time.After(timeout):
		return nil, fmt.Errorf("timeout waiting for response after %d seconds", timeoutSeconds)
	}
}

// SendQueueCommand sends a queued command to a machine
func SendQueueCommand(nc *nats.Conn, js nats.JetStreamContext, request puda.CommandRequest, runID, userID, username string, store *db.Store) (*puda.NATSMessage, error) {
	subject := fmt.Sprintf("puda.%s.cmd.queue", request.MachineID)
	payload := BuildCommandPayload(request, request.MachineID, runID, userID, username)

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command payload: %w", err)
	}

	// Subscribe to response stream before publishing
	responseSubject := fmt.Sprintf("puda.%s.cmd.response.queue", request.MachineID)
	responseCh := make(chan *puda.NATSMessage, 1)

	// Create ephemeral consumer for response stream
	sub, err := js.Subscribe(responseSubject, func(msg *nats.Msg) {
		var response puda.NATSMessage
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
	// Insert into database if response exists and store is available
	if store != nil && response.Response != nil {
		if err := store.InsertCommandLog(response, "queue"); err != nil {
			log.Printf("Failed to insert command log: %v", err)
			// Don't fail the command if logging fails
		}
	}
	return response, nil
}

// SendStartCommand sends a START command to a machine
func SendStartCommand(nc *nats.Conn, js nats.JetStreamContext, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       "start",
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(nc, js, request, runID, userID, username, timeoutSeconds, store)
}

// SendCompleteCommand sends a COMPLETE command to a machine
func SendCompleteCommand(nc *nats.Conn, js nats.JetStreamContext, machineID, runID, userID, username string, timeoutSeconds int, stepNumber int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       "complete",
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: stepNumber,
		Version:    "1.0",
	}
	return SendImmediateCommand(nc, js, request, runID, userID, username, timeoutSeconds, store)
}

// SendResetCommand sends a RESET immediate command to a machine
func SendResetCommand(nc *nats.Conn, js nats.JetStreamContext, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandReset,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(nc, js, request, runID, userID, username, timeoutSeconds, store)
}
