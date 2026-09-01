package nats

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/nats-io/nats.go"
)

// SendImmediateCommand sends an immediate command to a machine.
func SendImmediateCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	return SendImmediateCommandWithContext(context.Background(), &sync.Mutex{}, js, dispatcher, request, runID, userID, username, timeoutSeconds, store)
}

// SendImmediateCommandWithContext interlocks cancellation with the actual NATS
// publication and releases the interlock before waiting for the response.
func SendImmediateCommandWithContext(ctx context.Context, interlock *sync.Mutex, js nats.JetStreamContext, dispatcher *ResponseDispatcher, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	return sendImmediateCommandWithContext(ctx, interlock, js, dispatcher, request, runID, userID, username, timeoutSeconds, store, nil)
}

func publishStartCommandWithCancellation(ctx context.Context, interlock *sync.Mutex, onAttempt func(), publish func() error) error {
	interlock.Lock()
	defer interlock.Unlock()
	if err := ctx.Err(); err != nil {
		return err
	}
	if onAttempt != nil {
		onAttempt()
	}
	return publish()
}

func waitForImmediateResponse(ctx context.Context, responseCh <-chan *puda.NATSMessage, timeout time.Duration) (*puda.NATSMessage, error) {
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case response := <-responseCh:
		return response, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-timer.C:
		return nil, context.DeadlineExceeded
	}
}

func sendImmediateCommandWithContext(ctx context.Context, interlock *sync.Mutex, js nats.JetStreamContext, dispatcher *ResponseDispatcher, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int, store *db.Store, onPublishAttempt func()) (*puda.NATSMessage, error) {
	subject := fmt.Sprintf("puda.%s.cmd.immediate", request.MachineID)
	payload := BuildCommandPayload(request, request.MachineID, runID, userID, username)

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command payload: %w", err)
	}

	responseCh := dispatcher.Register(runID, request.StepNumber, request.MachineID)
	defer dispatcher.Unregister(runID, request.StepNumber, request.MachineID)

	err = publishStartCommandWithCancellation(ctx, interlock, onPublishAttempt, func() error {
		_, publishErr := js.Publish(subject, payloadJSON)
		return publishErr
	})
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, fmt.Errorf("failed to publish command: %w", err)
	}

	response, err := waitForImmediateResponse(ctx, responseCh, time.Duration(timeoutSeconds)*time.Second)
	if err != nil {
		if errors.Is(err, context.DeadlineExceeded) {
			return nil, fmt.Errorf("timeout waiting for response after %d seconds", timeoutSeconds)
		}
		return nil, err
	}
	if store != nil && response.Response != nil {
		if err := store.InsertCommandLog(response, "immediate"); err != nil {
			log.Printf("Failed to insert command log: %v", err)
		}
	}
	return response, nil
}

// SendQueueCommand sends a queued command to a machine
func SendQueueCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, request puda.CommandRequest, runID, userID, username string, store *db.Store) (*puda.NATSMessage, error) {
	return SendQueueCommandWithContext(context.Background(), &sync.Mutex{}, js, dispatcher, request, runID, userID, username, store)
}

func publishQueueCommandWithCancellation(ctx context.Context, interlock *sync.Mutex, publish func() error) error {
	interlock.Lock()
	defer interlock.Unlock()
	if err := ctx.Err(); err != nil {
		return err
	}
	return publish()
}

// SendQueueCommandWithContext interlocks cancellation with each actual NATS
// publication. The interlock is released before retries and response waiting.
func SendQueueCommandWithContext(ctx context.Context, interlock *sync.Mutex, js nats.JetStreamContext, dispatcher *ResponseDispatcher, request puda.CommandRequest, runID, userID, username string, store *db.Store) (*puda.NATSMessage, error) {
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
		err = publishQueueCommandWithCancellation(ctx, interlock, func() error {
			_, publishErr := js.Publish(subject, payloadJSON, nats.AckWait(publishAckWait))
			return publishErr
		})
		if err == nil {
			break
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if attempt < maxPublishRetries {
			log.Printf("Publish attempt %d/%d failed: %v; retrying...", attempt, maxPublishRetries, err)
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(time.Second * time.Duration(attempt)):
			}
		} else {
			return nil, fmt.Errorf("failed to publish command after %d attempts: %w", maxPublishRetries, err)
		}
	}

	// Wait for response (no timeout)
	var response *puda.NATSMessage
	select {
	case response = <-responseCh:
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	if store != nil && response.Response != nil {
		if err := store.InsertCommandLog(response, "queue"); err != nil {
			log.Printf("Failed to insert command log: %v", err)
		}
	}
	return response, nil
}

// SendStartCommand sends a START command to a machine.
func SendStartCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	return SendStartCommandWithContext(context.Background(), &sync.Mutex{}, js, dispatcher, machineID, runID, userID, username, timeoutSeconds, store, nil)
}

// SendStartCommandWithContext sends START with cancellation interlocked against
// publication. onPublishAttempt runs under that interlock immediately before the
// publish, allowing cleanup eligibility to be recorded even if the response is lost.
func SendStartCommandWithContext(ctx context.Context, interlock *sync.Mutex, js nats.JetStreamContext, dispatcher *ResponseDispatcher, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store, onPublishAttempt func()) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandStart,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return sendImmediateCommandWithContext(ctx, interlock, js, dispatcher, request, runID, userID, username, timeoutSeconds, store, onPublishAttempt)
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

// SendPauseCommand sends a PAUSE immediate command to a machine
func SendPauseCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandPause,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(js, dispatcher, request, runID, userID, username, timeoutSeconds, store)
}

// SendResumeCommand sends a RESUME immediate command to a machine
func SendResumeCommand(js nats.JetStreamContext, dispatcher *ResponseDispatcher, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandResume,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
		Version:    "1.0",
	}
	return SendImmediateCommand(js, dispatcher, request, runID, userID, username, timeoutSeconds, store)
}
