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
	if machinePingCmd.Flags().Lookup("timeout") == nil {
		t.Fatal("ping command must expose --timeout")
	}
	if machineCmd.PersistentFlags().Lookup("human") == nil {
		t.Fatal("machine command must expose --human")
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
		{MachineID: "first", Status: "pong", RunStatus: "busy", LatencyMS: 2.5, SDKVersion: "0.0.17", UptimeSeconds: 12.5, Description: "Liquid-handling robot."},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var buf bytes.Buffer
	writePingResults(&buf, results, true)
	output := buf.String()
	for _, want := range []string{"first: pong", "status=busy", "2.500ms", "sdk=0.0.17", "Liquid-handling robot.", "offline: failed: timeout"} {
		if !strings.Contains(output, want) {
			t.Fatalf("output missing %q: %s", want, output)
		}
	}
}

func TestWritePingResultsJSONIsDefault(t *testing.T) {
	results := []pudanats.PingResult{
		{MachineID: "first", Status: "pong", RunStatus: "busy", LatencyMS: 2.5, SDKVersion: "0.0.17", UptimeSeconds: 12.5, Description: "Liquid-handling robot."},
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
	if payload.Results[0].MachineID != "first" || payload.Results[0].Description != "Liquid-handling robot." || payload.Results[1].Error != "timeout" {
		t.Fatalf("unexpected results: %+v", payload.Results)
	}
}

func TestWriteListResultsJSONIsDefault(t *testing.T) {
	pongs := []pudanats.PingResult{
		{MachineID: "biologic", Status: "pong", Description: "Potentiostat."},
		{MachineID: "first", Status: "pong"},
	}
	var buf bytes.Buffer
	if err := writeListResults(&buf, pongs, false); err != nil {
		t.Fatal(err)
	}
	var payload struct {
		Machines []listedMachine `json:"machines"`
		Count    int             `json:"count"`
	}
	if err := json.Unmarshal(buf.Bytes(), &payload); err != nil {
		t.Fatalf("default output is not JSON: %v\n%s", err, buf.String())
	}
	if payload.Count != 2 {
		t.Fatalf("got %+v", payload)
	}
	if payload.Machines[0] != (listedMachine{MachineID: "biologic", Description: "Potentiostat."}) {
		t.Fatalf("got %+v", payload.Machines[0])
	}
	if payload.Machines[1] != (listedMachine{MachineID: "first"}) {
		t.Fatalf("got %+v", payload.Machines[1])
	}
}

func TestWriteListResultsHuman(t *testing.T) {
	var buf bytes.Buffer
	if err := writeListResults(&buf, []pudanats.PingResult{
		{MachineID: "first", Description: "Software-only test machine."},
	}, true); err != nil {
		t.Fatal(err)
	}
	if got, want := buf.String(), "1 machines found:\n  first: Software-only test machine.\n"; got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}
