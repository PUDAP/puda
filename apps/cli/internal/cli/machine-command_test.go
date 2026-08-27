package cli

import (
	"bytes"
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

func TestSplitImmediateCommandTargets(t *testing.T) {
	onlineMachines := map[string]struct{}{
		"first": {},
		"third": {},
	}

	online, offline := splitImmediateCommandTargets([]string{"first", "second", "third"}, onlineMachines)

	if want := []string{"first", "third"}; !reflect.DeepEqual(online, want) {
		t.Fatalf("online = %#v, want %#v", online, want)
	}
	if want := []string{"second"}; !reflect.DeepEqual(offline, want) {
		t.Fatalf("offline = %#v, want %#v", offline, want)
	}
}

func TestWriteImmediateCommandResultSuccess(t *testing.T) {
	var buf bytes.Buffer

	writeImmediateCommandResult(&buf, "Reset", "first", nil)

	want := "first: reset command sent successfully\n"
	if got := buf.String(); got != want {
		t.Fatalf("output = %q, want %q", got, want)
	}
}

func TestWriteImmediateCommandResultFailure(t *testing.T) {
	var buf bytes.Buffer

	writeImmediateCommandResult(&buf, "Reset", "second", errors.New("offline or does not exist"))

	want := "second: reset command failed: offline or does not exist\n"
	if got := buf.String(); got != want {
		t.Fatalf("output = %q, want %q", got, want)
	}
}

func TestWriteMachineCommandResultsJSONIsDefault(t *testing.T) {
	results := []machineCommandResult{
		{MachineID: "first", Status: "ok"},
		{MachineID: "offline", Status: "error", Error: "offline or does not exist"},
	}
	var buf bytes.Buffer
	if err := writeMachineCommandResults(&buf, "reset", "run-1", "sent", results, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Command   string                 `json:"command"`
		RunID     string                 `json:"run_id"`
		Results   []machineCommandResult `json:"results"`
		Count     int                    `json:"count"`
		Succeeded int                    `json:"succeeded"`
		Failed    int                    `json:"failed"`
	}
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatalf("default output is not JSON: %v\n%s", err, buf.String())
	}
	if payload.Command != "reset" || payload.RunID != "run-1" || payload.Count != 2 || payload.Succeeded != 1 || payload.Failed != 1 {
		t.Fatalf("got %+v", payload)
	}
}

func TestResolveRunIDUsesProvided(t *testing.T) {
	got := resolveRunID("custom-run-id")
	if got != "custom-run-id" {
		t.Fatalf("resolveRunID = %q, want %q", got, "custom-run-id")
	}
}

func TestResolveRunIDGeneratesUUID(t *testing.T) {
	got := resolveRunID("")
	if got == "" {
		t.Fatal("resolveRunID returned empty string")
	}
	if len(got) != 36 {
		t.Fatalf("resolveRunID = %q, want uuidv4 length 36", got)
	}
}

func TestParseMachineRunObject(t *testing.T) {
	tests := []struct {
		name  string
		value string
		want  map[string]interface{}
		err   string
	}{
		{
			name: "empty value produces an empty object",
			want: map[string]interface{}{},
		},
		{
			name:  "parses JSON values without converting their types",
			value: `{"slot":"A2","volume":12.5,"enabled":true,"channels":[0,1]}`,
			want: map[string]interface{}{
				"slot":     "A2",
				"volume":   12.5,
				"enabled":  true,
				"channels": []interface{}{float64(0), float64(1)},
			},
		},
		{
			name:  "rejects non objects",
			value: `["A2"]`,
			err:   "params must be a valid JSON object",
		},
		{
			name:  "rejects null",
			value: `null`,
			err:   "params must be a JSON object, not null",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseMachineRunObject("params", tt.value)
			if tt.err != "" {
				if err == nil || !strings.Contains(err.Error(), tt.err) {
					t.Fatalf("parseMachineRunObject() error = %v, want containing %q", err, tt.err)
				}
				return
			}
			if err != nil {
				t.Fatalf("parseMachineRunObject() error = %v", err)
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Fatalf("parseMachineRunObject() = %#v, want %#v", got, tt.want)
			}
		})
	}
}

func TestNewImmediateMachineCommand(t *testing.T) {
	runID := ""
	cmd := newImmediateMachineCommand(immediateMachineCommandConfig{
		name:      "start",
		short:     "Start a run on machine(s)",
		label:     "Start",
		runIDFlag: &runID,
	})

	if got, want := cmd.Use, "start <machine_ids>"; got != want {
		t.Fatalf("Use = %q, want %q", got, want)
	}
	if !strings.Contains(cmd.Long, "puda machine start biologic,first") {
		t.Fatalf("Long = %q, want machine ID example", cmd.Long)
	}
	if !strings.Contains(cmd.Long, "Use --run-id") {
		t.Fatalf("Long = %q, want run ID documentation", cmd.Long)
	}
}

func TestMachineRunCommand(t *testing.T) {
	if got, want := machineRunCmd.Use, "run <machine_id> <command_name> [params_json]"; got != want {
		t.Fatalf("Use = %q, want %q", got, want)
	}
	if !strings.Contains(machineRunCmd.Long, "without sending START or COMPLETE") {
		t.Fatalf("Long = %q, want direct queue documentation", machineRunCmd.Long)
	}
	if machineRunCmd.Flags().Lookup("params") == nil {
		t.Fatal("expected --params flag")
	}
	if machineRunCmd.Flags().Lookup("kwargs") == nil {
		t.Fatal("expected --kwargs flag")
	}
}

func TestImmediateCommandResponseError(t *testing.T) {
	message := "machine is busy"
	tests := []struct {
		name     string
		response *puda.NATSMessage
		want     string
	}{
		{name: "no response"},
		{
			name: "successful response",
			response: &puda.NATSMessage{Response: &puda.CommandResponse{
				Status: puda.StatusSuccess,
			}},
		},
		{
			name: "error response without message",
			response: &puda.NATSMessage{Response: &puda.CommandResponse{
				Status: puda.StatusError,
			}},
			want: "unknown error",
		},
		{
			name: "error response with message",
			response: &puda.NATSMessage{Response: &puda.CommandResponse{
				Status:  puda.StatusError,
				Message: &message,
			}},
			want: message,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := immediateCommandResponseError(tt.response)
			if tt.want == "" && err != nil {
				t.Fatalf("immediateCommandResponseError() = %v, want nil", err)
			}
			if tt.want != "" && (err == nil || err.Error() != tt.want) {
				t.Fatalf("immediateCommandResponseError() = %v, want %q", err, tt.want)
			}
		})
	}
}

func TestQueueCommandResponseError(t *testing.T) {
	if err := queueCommandResponseError(nil); err == nil || err.Error() != "command returned no response data" {
		t.Fatalf("queueCommandResponseError(nil) = %v, want missing response error", err)
	}

	response := &puda.NATSMessage{Response: &puda.CommandResponse{Status: puda.StatusSuccess}}
	if err := queueCommandResponseError(response); err != nil {
		t.Fatalf("queueCommandResponseError(success) = %v, want nil", err)
	}
}
