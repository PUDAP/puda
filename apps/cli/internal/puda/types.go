package puda

import "encoding/json"

// CommandRequest represents a command request
type CommandRequest struct {
	Name       string                 `json:"name"`
	Params     map[string]interface{} `json:"params"`
	Kwargs     map[string]interface{} `json:"kwargs,omitempty"`
	StepNumber int                    `json:"step_number"`
	Version    string                 `json:"version,omitempty"`
	MachineID  string                 `json:"machine_id"`
}

// ImmediateCommand is the command name for immediate commands (matches puda.models.ImmediateCommand).
const (
	ImmediateCommandStart    = "start"
	ImmediateCommandComplete = "complete"
	ImmediateCommandPause    = "pause"
	ImmediateCommandResume   = "resume"
	ImmediateCommandCancel   = "cancel"
	ImmediateCommandReset    = "reset"
)

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

// ProtocolFile represents the structure of a protocol JSON file
type ProtocolFile struct {
	ProjectID   string           `json:"project_id"`
	ProtocolID  string           `json:"protocol_id"`
	UserID      string           `json:"user_id"`
	Username    string           `json:"username"`
	Description string           `json:"description"`
	Timestamp   string           `json:"timestamp"`
	Commands    []CommandRequest `json:"commands"`
}

type ConfigUser struct {
	Username string `json:"username"`
	UserID   string `json:"user_id"`
}

// UnmarshalJSON keeps config loading compatible with the legacy "userid" key.
func (u *ConfigUser) UnmarshalJSON(data []byte) error {
	type configUserAlias struct {
		Username     string `json:"username"`
		UserID       string `json:"user_id"`
		LegacyUserID string `json:"userid"`
	}

	var alias configUserAlias
	if err := json.Unmarshal(data, &alias); err != nil {
		return err
	}

	u.Username = alias.Username
	u.UserID = alias.UserID
	if u.UserID == "" {
		u.UserID = alias.LegacyUserID
	}

	return nil
}

type ConfigDatabase struct {
	Path string `json:"path"`
}

// Env represents a named connection environment with NATS endpoints.
type Env struct {
	NATSServers string `json:"nats_servers"`
	Description string `json:"description"`
}

// BuiltinEnvs contains the hardcoded connection environments.
var BuiltinEnvs = map[string]Env{
	"bears": {NATSServers: "nats://100.109.131.12:4222,nats://100.109.131.12:4223,nats://100.109.131.12:4224", Description: "create tower (dev work)"},
	"imre":  {NATSServers: "nats://100.109.131.12:4222,nats://100.109.131.12:4223,nats://100.109.131.12:4224", Description: "CuspAI setup"},
	"ntu":   {NATSServers: "nats://100.109.131.12:4223,nats://100.109.131.12:4223,nats://100.109.131.12:4224", Description: "PUDA NTU setup"},
}

// GlobalConfig represents the structure of the global PUDA CLI configuration file.
// This is stored in the user's config directory and only contains user identity.
type GlobalConfig struct {
	User      ConfigUser `json:"user"`
	ActiveEnv string     `json:"active_env,omitempty"`
}

// ActiveEnvNATSServers returns the NATS server URLs for the active env.
// Falls back to "bears" if the env is not set or not found.
func (g *GlobalConfig) ActiveEnvNATSServers() string {
	if e, ok := BuiltinEnvs[g.ActiveEnv]; ok {
		return e.NATSServers
	}
	return BuiltinEnvs["bears"].NATSServers
}

// ProjectConfig represents the structure of the project-level PUDA CLI config.json file.
// This is stored in each project directory and contains project-specific settings.
type ProjectConfig struct {
	User        ConfigUser     `json:"user"`
	Database    ConfigDatabase `json:"database"`
	ProjectID   string         `json:"project_id"`
	ProjectRoot string         `json:"project_root"`
}
