package edge

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

func safeID(id string) string           { return strings.ReplaceAll(id, ".", "-") }
func HeartbeatSubject(id string) string { return fmt.Sprintf("puda.%s.tlm.heartbeat", safeID(id)) }
func PositionSubject(id string) string  { return fmt.Sprintf("puda.%s.tlm.pos", safeID(id)) }
func HealthSubject(id string) string    { return fmt.Sprintf("puda.%s.tlm.health", safeID(id)) }
func QueueSubject(id string) string     { return fmt.Sprintf("puda.%s.cmd.queue", safeID(id)) }
func ImmediateSubject(id string) string { return fmt.Sprintf("puda.%s.cmd.immediate", safeID(id)) }
func QueueResponseSubject(id string) string {
	return fmt.Sprintf("puda.%s.cmd.response.queue", safeID(id))
}
func ImmediateResponseSubject(id string) string {
	return fmt.Sprintf("puda.%s.cmd.response.immediate", safeID(id))
}

func HeartbeatPayload() ([]byte, error) {
	return json.Marshal(map[string]any{"timestamp": time.Now().UTC().Format(time.RFC3339)})
}
func PositionPayload(x, y, z float64) ([]byte, error) {
	return json.Marshal(map[string]any{"timestamp": time.Now().UTC().Format(time.RFC3339), "x": x, "y": y, "z": z})
}
func HealthPayload(cpu, mem float64) ([]byte, error) {
	return json.Marshal(map[string]any{"timestamp": time.Now().UTC().Format(time.RFC3339), "cpu": cpu, "mem": mem, "temp": nil})
}

func CommandPayload(machineID, runID string, stepNumber int, name string) ([]byte, error) {
	now := time.Now().UTC().Format(time.RFC3339)
	return json.Marshal(map[string]any{
		"header": map[string]any{
			"version": "1.0", "message_type": "command",
			"user_id": "puda-loadgen", "username": "puda-loadgen",
			"machine_id": safeID(machineID), "run_id": runID, "timestamp": now,
		},
		"command": map[string]any{
			"name": name, "params": map[string]any{}, "step_number": stepNumber,
			"version": "1.0", "machine_id": safeID(machineID),
		},
	})
}

func SuccessResponse(request []byte) ([]byte, error) {
	var message map[string]any
	if err := json.Unmarshal(request, &message); err != nil {
		return nil, err
	}
	header, ok := message["header"].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("command message has no header")
	}
	now := time.Now().UTC().Format(time.RFC3339)
	header["message_type"] = "response"
	header["timestamp"] = now
	message["response"] = map[string]any{
		"status":       "success",
		"completed_at": now,
		"data":         map[string]any{"simulated": true},
	}
	return json.Marshal(message)
}
