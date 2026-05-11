package nats

import (
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

// GetCurrentTimestamp returns the current timestamp in UTC format
func GetCurrentTimestamp() string {
	return time.Now().UTC().Format("2006-01-02T15:04:05Z")
}

// BuildCommandPayload builds a NATS message payload from a command request
func BuildCommandPayload(request puda.CommandRequest, machineID, runID, userID, username string) puda.NATSMessage {
	if request.Version == "" {
		request.Version = "1.0"
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
		Command: &request,
	}
}

// GetResponseMessage extracts a human-readable message from a response
func GetResponseMessage(response *puda.NATSMessage) string {
	if response.Response == nil {
		return "unknown error"
	}
	if response.Response.Message != nil {
		return *response.Response.Message
	}
	if response.Response.Code != nil {
		return *response.Response.Code
	}
	return "unknown error"
}
