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

// ErrMachineOffline reports that nothing answers the machine's immediate
// subject: the broker returned no responders, so the command was not delivered.
var ErrMachineOffline = errors.New("no responders: machine offline or does not exist")

// SendImmediateCommand sends an immediate command to a machine over core NATS
// request/reply and waits for the edge's reply.
func SendImmediateCommand(nc *nats.Conn, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	return SendImmediateCommandWithContext(context.Background(), &sync.Mutex{}, nc, request, runID, userID, username, timeoutSeconds, store)
}

// SendImmediateCommandWithContext interlocks cancellation with the actual NATS
// publication and releases the interlock before waiting for the reply.
func SendImmediateCommandWithContext(ctx context.Context, interlock *sync.Mutex, nc *nats.Conn, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	return sendImmediateCommandWithContext(ctx, interlock, nc, request, runID, userID, username, timeoutSeconds, store, nil)
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

// classifyImmediateReply interprets one message on the request inbox: the
// edge's response, a no-responders status (offline is true), or neither
// (unreadable; ignored).
func classifyImmediateReply(msg *nats.Msg) (response *puda.NATSMessage, offline bool) {
	if len(msg.Data) == 0 && msg.Header.Get("Status") == "503" {
		return nil, true
	}
	plain, err := Open(msg.Subject, msg.Data)
	if err != nil {
		return nil, false
	}
	var reply puda.NATSMessage
	if err := json.Unmarshal(plain, &reply); err != nil || reply.Response == nil {
		return nil, false
	}
	return &reply, false
}

// waitForImmediateReply reads inbox replies until the edge responds, the
// broker reports no responders, the timeout passes, or ctx is cancelled.
func waitForImmediateReply(ctx context.Context, next func(context.Context) (*nats.Msg, error), timeout time.Duration) (*puda.NATSMessage, error) {
	waitCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	for {
		msg, err := next(waitCtx)
		if err != nil {
			if ctxErr := ctx.Err(); ctxErr != nil {
				return nil, ctxErr
			}
			if waitCtx.Err() != nil {
				return nil, fmt.Errorf("no reply within %gs; outcome unknown (the command may have run); immediate commands are safe to retry", timeout.Seconds())
			}
			// nats.go turns the broker's 503 status reply into ErrNoResponders.
			if errors.Is(err, nats.ErrNoResponders) {
				return nil, ErrMachineOffline
			}
			return nil, fmt.Errorf("failed to read command reply: %w", err)
		}
		response, offline := classifyImmediateReply(msg)
		if offline {
			return nil, ErrMachineOffline
		}
		if response != nil {
			return response, nil
		}
	}
}

func sendImmediateCommandWithContext(ctx context.Context, interlock *sync.Mutex, nc *nats.Conn, request puda.CommandRequest, runID, userID, username string, timeoutSeconds int, store *db.Store, onPublishAttempt func()) (*puda.NATSMessage, error) {
	subject := fmt.Sprintf("puda.%s.cmd.immediate", request.MachineID)
	payload := BuildCommandPayload(request, request.MachineID, runID, userID, username)

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command payload: %w", err)
	}
	payloadJSON, err = Seal(subject, payloadJSON)
	if err != nil {
		return nil, err
	}

	// Read replies on an own inbox (like ping) and skip unreadable ones.
	inbox := nats.NewInbox()
	sub, err := nc.SubscribeSync(inbox)
	if err != nil {
		return nil, fmt.Errorf("failed to subscribe to command reply: %w", err)
	}
	defer sub.Unsubscribe()

	err = publishStartCommandWithCancellation(ctx, interlock, onPublishAttempt, func() error {
		return nc.PublishMsg(&nats.Msg{Subject: subject, Reply: inbox, Data: payloadJSON})
	})
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, fmt.Errorf("failed to publish command: %w", err)
	}

	response, err := waitForImmediateReply(ctx, sub.NextMsgWithContext, time.Duration(timeoutSeconds)*time.Second)
	if err != nil {
		return nil, err
	}
	if store != nil {
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
	payloadJSON, err = Seal(subject, payloadJSON)
	if err != nil {
		return nil, err
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
func SendStartCommand(nc *nats.Conn, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	return SendStartCommandWithContext(context.Background(), &sync.Mutex{}, nc, machineID, runID, userID, username, timeoutSeconds, store, nil)
}

// SendStartCommandWithContext sends START with cancellation interlocked against
// publication. onPublishAttempt runs under that interlock immediately before the
// publish, allowing cleanup eligibility to be recorded even if the response is lost.
func SendStartCommandWithContext(ctx context.Context, interlock *sync.Mutex, nc *nats.Conn, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store, onPublishAttempt func()) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandStart,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
	}
	return sendImmediateCommandWithContext(ctx, interlock, nc, request, runID, userID, username, timeoutSeconds, store, onPublishAttempt)
}

// SendCompleteCommand sends a COMPLETE command to a machine. With abort the
// edge stops the running queued command instead of refusing with
// EXECUTION_LOCKED.
func SendCompleteCommand(nc *nats.Conn, machineID, runID, userID, username string, timeoutSeconds int, stepNumber int, abort bool, store *db.Store) (*puda.NATSMessage, error) {
	params := make(map[string]interface{})
	if abort {
		params["abort"] = true
	}
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandComplete,
		MachineID:  machineID,
		Params:     params,
		StepNumber: stepNumber,
	}
	return SendImmediateCommand(nc, request, runID, userID, username, timeoutSeconds, store)
}

// SendResetCommand sends a RESET immediate command to a machine
func SendResetCommand(nc *nats.Conn, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandReset,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
	}
	return SendImmediateCommand(nc, request, runID, userID, username, timeoutSeconds, store)
}

// SendEstopCommand sends an ESTOP immediate command to a machine.
func SendEstopCommand(nc *nats.Conn, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandEstop,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
	}
	return SendImmediateCommand(nc, request, runID, userID, username, timeoutSeconds, store)
}

// SendPauseCommand sends a PAUSE immediate command to a machine
func SendPauseCommand(nc *nats.Conn, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandPause,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
	}
	return SendImmediateCommand(nc, request, runID, userID, username, timeoutSeconds, store)
}

// SendResumeCommand sends a RESUME immediate command to a machine
func SendResumeCommand(nc *nats.Conn, machineID, runID, userID, username string, timeoutSeconds int, store *db.Store) (*puda.NATSMessage, error) {
	request := puda.CommandRequest{
		Name:       puda.ImmediateCommandResume,
		MachineID:  machineID,
		Params:     make(map[string]interface{}),
		StepNumber: 0,
	}
	return SendImmediateCommand(nc, request, runID, userID, username, timeoutSeconds, store)
}
