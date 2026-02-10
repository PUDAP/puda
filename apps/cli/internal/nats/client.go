package nats

import (
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/nats-io/nats.go"
)

// SendImmediateCommand sends an immediate command to a machine
func SendImmediateCommand(nc *nats.Conn, js nats.JetStreamContext, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int) (*puda.NATSMessage, error) {
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
		return response, nil
	case <-time.After(timeout):
		return nil, fmt.Errorf("timeout waiting for response after %d seconds", timeoutSeconds)
	}
}

// SendQueueCommand sends a queued command to a machine
func SendQueueCommand(nc *nats.Conn, js nats.JetStreamContext, request puda.CommandRequest, runID, userID, username string) (*puda.NATSMessage, error) {
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

	// Publish command
	_, err = js.Publish(subject, payloadJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to publish command: %w", err)
	}

	// Wait for response (no timeout)
	response := <-responseCh
	return response, nil
}

// SendStartCommand sends a START command to a machine
func SendStartCommand(nc *nats.Conn, js nats.JetStreamContext, machineID, runID, userID, username string, timeoutSeconds int) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       "start",
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(nc, js, request, runID, userID, username, timeoutSeconds)
}

// SendCompleteCommand sends a COMPLETE command to a machine
func SendCompleteCommand(nc *nats.Conn, js nats.JetStreamContext, machineID, runID, userID, username string, timeoutSeconds int) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       "complete",
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(nc, js, request, runID, userID, username, timeoutSeconds)
}
