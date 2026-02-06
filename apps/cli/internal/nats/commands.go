package nats

import (
	"encoding/json"
	"fmt"
	"os"
	"time"
)

// LoadCommands loads commands from a JSON file
func LoadCommands(filePath string) ([]CommandRequest, error) {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to read commands file: %w", err)
	}

	var commands []CommandRequest
	if err := json.Unmarshal(data, &commands); err != nil {
		return nil, fmt.Errorf("failed to parse JSON: %w", err)
	}

	return commands, nil
}

// GetCurrentTimestamp returns the current timestamp in UTC format
func GetCurrentTimestamp() string {
	return time.Now().UTC().Format("2006-01-02T15:04:05Z")
}

// BuildCommandPayload builds a NATS message payload from a command request
func BuildCommandPayload(request CommandRequest, machineID, runID, userID, username string) NATSMessage {
	if request.Version == "" {
		request.Version = "1.0"
	}
	runIDPtr := &runID
	return NATSMessage{
		Header: MessageHeader{
			Version:     "1.0",
			MessageType: MessageTypeCommand,
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
func GetResponseMessage(response *NATSMessage) string {
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
