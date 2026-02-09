package nats

import (
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

// LoadProtocol loads a protocol file (JSON with commands and metadata) from disk
func LoadProtocol(filePath string) (*puda.ProtocolFile, error) {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to read commands file: %w", err)
	}

	var protocolFile puda.ProtocolFile
	if err := json.Unmarshal(data, &protocolFile); err != nil {
		return nil, fmt.Errorf("failed to parse JSON: expected an object with 'commands' field: %w", err)
	}

	if len(protocolFile.Commands) == 0 {
		return nil, fmt.Errorf("commands array is empty or missing")
	}

	// Initialize nil params to empty maps
	for i := range protocolFile.Commands {
		if protocolFile.Commands[i].Params == nil {
			protocolFile.Commands[i].Params = make(map[string]interface{})
		}
	}

	return &protocolFile, nil
}

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
