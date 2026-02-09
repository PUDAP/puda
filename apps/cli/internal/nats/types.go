package nats

// CommandRequest represents a command request
type CommandRequest struct {
	Name       string                 `json:"name"`
	Params     map[string]interface{} `json:"params"`
	Kwargs     map[string]interface{} `json:"kwargs,omitempty"`
	StepNumber int                    `json:"step_number"`
	Version    string                 `json:"version,omitempty"`
	MachineID  string                 `json:"machine_id"`
}

// CommandResponseStatus represents the status of a command response
type CommandResponseStatus string

const (
	StatusSuccess CommandResponseStatus = "success"
	StatusError   CommandResponseStatus = "error"
)

// CommandResponse represents a command response
type CommandResponse struct {
	Status      CommandResponseStatus  `json:"status"`
	CompletedAt string                 `json:"completed_at"`
	Code        *string                `json:"code,omitempty"`
	Message     *string                `json:"message,omitempty"`
	Data        map[string]interface{} `json:"data,omitempty"`
}

// MessageType represents the type of NATS message
type MessageType string

const (
	MessageTypeCommand  MessageType = "command"
	MessageTypeResponse MessageType = "response"
)

// MessageHeader represents the header of a NATS message
type MessageHeader struct {
	Version     string      `json:"version"`
	MessageType MessageType `json:"message_type"`
	UserID      string      `json:"user_id"`
	Username    string      `json:"username"`
	MachineID   string      `json:"machine_id"`
	RunID       *string     `json:"run_id,omitempty"`
	Timestamp   string      `json:"timestamp"`
}

// NATSMessage represents a complete NATS message
type NATSMessage struct {
	Header   MessageHeader    `json:"header"`
	Command  *CommandRequest  `json:"command,omitempty"`
	Response *CommandResponse `json:"response,omitempty"`
}

// MachineHeartbeat represents a machine's heartbeat information
type MachineHeartbeat struct {
	MachineID string `json:"machine_id"`
	Timestamp string `json:"timestamp"`
}
