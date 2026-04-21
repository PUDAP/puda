package nats

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	natsio "github.com/nats-io/nats.go"
)

// UpdateParams describes the source a PUDA edge should update from.
type UpdateParams struct {
	// SourceType is "git" or "docker".
	SourceType string
	// Ref is the repo URL (git) or image:tag (docker).
	//
	// For git it is optional: when set, the edge re-points its "origin" remote
	// to this URL before fetching; when empty, the edge fetches from the
	// existing "origin". For docker it is required (the image:tag to pull).
	Ref string
	// Checkout is the git branch, tag, or commit SHA the edge should reset to
	// (git only; ignored for docker). Empty means the edge uses its default
	// ("main").
	Checkout string
}

// WaitForHeartbeat blocks until a heartbeat on puda.<machine_id>.tlm.heartbeat
// arrives, or returns an error on timeout. Uses core NATS (no JetStream).
func WaitForHeartbeat(nc *natsio.Conn, machineID string, timeout time.Duration) error {
	subject := fmt.Sprintf("puda.%s.tlm.heartbeat", strings.ReplaceAll(machineID, ".", "-"))
	seen := make(chan struct{}, 1)

	sub, err := nc.Subscribe(subject, func(_ *natsio.Msg) {
		select {
		case seen <- struct{}{}:
		default:
		}
	})
	if err != nil {
		return fmt.Errorf("failed to subscribe to heartbeat: %w", err)
	}
	defer sub.Unsubscribe()

	select {
	case <-seen:
		return nil
	case <-time.After(timeout):
		return fmt.Errorf("no heartbeat from %s within %s -- is the edge process running?", machineID, timeout)
	}
}

// SendUpdateCommand publishes an update command to puda.<machine_id>.update via
// core NATS (not JetStream), waits for the edge's response on
// puda.<machine_id>.update.response, and returns it.
//
// The edge applies the update and then exits; the update.response message IS
// the confirmation that the pull worked.
func SendUpdateCommand(
	nc *natsio.Conn,
	machineID, userID, username string,
	params UpdateParams,
	timeout time.Duration,
) (*puda.NATSMessage, error) {
	safeID := strings.ReplaceAll(machineID, ".", "-")
	updateSubject := fmt.Sprintf("puda.%s.update", safeID)
	responseSubject := fmt.Sprintf("puda.%s.update.response", safeID)

	runID := uuid.New().String()
	payload := buildUpdateMessage(machineID, runID, userID, username, params)
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal update payload: %w", err)
	}

	replies := make(chan *puda.NATSMessage, 1)
	sub, err := nc.Subscribe(responseSubject, func(msg *natsio.Msg) {
		var reply puda.NATSMessage
		if err := json.Unmarshal(msg.Data, &reply); err != nil {
			return
		}
		if reply.Header.RunID == nil || *reply.Header.RunID != runID {
			return
		}
		select {
		case replies <- &reply:
		default:
		}
	})
	if err != nil {
		return nil, fmt.Errorf("failed to subscribe to %s: %w", responseSubject, err)
	}
	defer sub.Unsubscribe()

	if err := nc.Publish(updateSubject, payloadJSON); err != nil {
		return nil, fmt.Errorf("failed to publish update command: %w", err)
	}
	if err := nc.Flush(); err != nil {
		return nil, fmt.Errorf("failed to flush NATS connection: %w", err)
	}

	select {
	case reply := <-replies:
		return reply, nil
	case <-time.After(timeout):
		return nil, fmt.Errorf("timed out waiting for update response after %s", timeout)
	}
}

func buildUpdateMessage(machineID, runID, userID, username string, params UpdateParams) puda.NATSMessage {
	cmdParams := map[string]interface{}{
		"source_type": params.SourceType,
	}
	if params.Ref != "" {
		cmdParams["ref"] = params.Ref
	}
	if params.Checkout != "" {
		cmdParams["checkout"] = params.Checkout
	}

	runIDPtr := &runID
	return puda.NATSMessage{
		Header: puda.MessageHeader{
			Version:     "1.0",
			MessageType: puda.MessageTypeCommand,
			UserID:      userID,
			Username:    username,
			MachineID:   machineID,
			RunID:       runIDPtr,
			Timestamp:   GetCurrentTimestamp(),
		},
		Command: &puda.CommandRequest{
			Name:       "update",
			MachineID:  machineID,
			Params:     cmdParams,
			StepNumber: 0,
			Version:    "1.0",
		},
	}
}
