package edge

import (
	"encoding/json"
	"testing"
)

func TestSubjectsMatchPUDAProtocol(t *testing.T) {
	id := "test-1"
	if got := HeartbeatSubject(id); got != "puda.test-1.tlm.heartbeat" {
		t.Fatalf("heartbeat=%q", got)
	}
	if got := PositionSubject(id); got != "puda.test-1.tlm.pos" {
		t.Fatalf("position=%q", got)
	}
	if got := HealthSubject(id); got != "puda.test-1.tlm.health" {
		t.Fatalf("health=%q", got)
	}
	if got := QueueSubject(id); got != "puda.test-1.cmd.queue" {
		t.Fatalf("queue=%q", got)
	}
	if got := ImmediateSubject(id); got != "puda.test-1.cmd.immediate" {
		t.Fatalf("immediate=%q", got)
	}
	if got := QueueResponseSubject(id); got != "puda.test-1.cmd.response.queue" {
		t.Fatalf("queue response=%q", got)
	}
	if got := ImmediateResponseSubject(id); got != "puda.test-1.cmd.response.immediate" {
		t.Fatalf("immediate response=%q", got)
	}
}

func TestTelemetryPayloadsAreValidJSON(t *testing.T) {
	if _, err := HeartbeatPayload(); err != nil {
		t.Fatal(err)
	}
	if _, err := PositionPayload(1, 2, 3); err != nil {
		t.Fatal(err)
	}
	if _, err := HealthPayload(20, 30); err != nil {
		t.Fatal(err)
	}
}

func TestSuccessResponsePreservesCorrelationFields(t *testing.T) {
	request := []byte(`{"header":{"version":"1.0","message_type":"command","machine_id":"test-1","run_id":"run-1","timestamp":"old"},"command":{"name":"echo","step_number":7,"machine_id":"test-1","params":{}}}`)
	response, err := SuccessResponse(request)
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(response, &got); err != nil {
		t.Fatal(err)
	}
	header := got["header"].(map[string]any)
	if header["message_type"] != "response" || header["run_id"] != "run-1" || header["machine_id"] != "test-1" {
		t.Fatalf("correlation fields lost: %v", header)
	}
	result := got["response"].(map[string]any)
	if result["status"] != "success" {
		t.Fatalf("response=%v", result)
	}
}

func TestCommandPayloadHasPUDACorrelationFields(t *testing.T) {
	payload, err := CommandPayload("test-1", "run-1", 7, "loadgen_ping")
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(payload, &got); err != nil {
		t.Fatal(err)
	}
	header := got["header"].(map[string]any)
	command := got["command"].(map[string]any)
	if header["machine_id"] != "test-1" || header["run_id"] != "run-1" || header["message_type"] != "command" {
		t.Fatalf("header=%v", header)
	}
	if command["name"] != "loadgen_ping" || command["step_number"] != float64(7) {
		t.Fatalf("command=%v", command)
	}
}
