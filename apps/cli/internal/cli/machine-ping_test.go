package cli

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
)

func TestMachinePingCommandMetadata(t *testing.T) {
	if got, want := machinePingCmd.Use, "ping <machine_ids>"; got != want {
		t.Fatalf("Use=%q want=%q", got, want)
	}
	if !strings.Contains(machinePingCmd.Long, "comma-separated") {
		t.Fatalf("Long=%q", machinePingCmd.Long)
	}
	if machinePingCmd.Flags().Lookup("timeout") == nil || machinePingCmd.Flags().Lookup("human") == nil {
		t.Fatal("ping command must expose --timeout and --human")
	}
}

func TestParseMachineIDsAcceptsCommaSeparatedAndMultipleArgs(t *testing.T) {
	got := parseMachineIDs([]string{"first, biologic", "third"})
	want := []string{"first", "biologic", "third"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("got=%v want=%v", got, want)
	}
}

func TestWritePingResultsHuman(t *testing.T) {
	results := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", RunStatus: "busy", LatencyMS: 2.5, SDKVersion: "0.0.17", UptimeSeconds: 12.5},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var buf bytes.Buffer
	writePingResults(&buf, results, true)
	output := buf.String()
	for _, want := range []string{"first: pong", "status=busy", "2.500ms", "sdk=0.0.17", "offline: failed: timeout"} {
		if !strings.Contains(output, want) {
			t.Fatalf("output missing %q: %s", want, output)
		}
	}
}

func TestWritePingResultsJSONIsDefault(t *testing.T) {
	results := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", RunStatus: "busy", LatencyMS: 2.5, SDKVersion: "0.0.17", UptimeSeconds: 12.5},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var buf bytes.Buffer
	if err := writePingResults(&buf, results, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Results   []pudanats.PingResult `json:"results"`
		Count     int                   `json:"count"`
		Responded int                   `json:"responded"`
		Failed    int                   `json:"failed"`
	}
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatalf("default output is not JSON: %v\n%s", err, buf.String())
	}
	if payload.Count != 2 || payload.Responded != 1 || payload.Failed != 1 {
		t.Fatalf("got counts count=%d responded=%d failed=%d", payload.Count, payload.Responded, payload.Failed)
	}
	if payload.Results[0].MachineID != "first" || payload.Results[1].Error != "timeout" {
		t.Fatalf("unexpected results: %+v", payload.Results)
	}
}
