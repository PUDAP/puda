package cli

import (
	"bytes"
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
	if machinePingCmd.Flags().Lookup("timeout") == nil || machinePingCmd.Flags().Lookup("json") == nil {
		t.Fatal("ping command must expose --timeout and --json")
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
		{MachineID: "first", Status: "pong", LatencyMS: 2.5, SDKVersion: "0.0.17", UptimeSeconds: 12.5},
		{MachineID: "offline", Status: "error", Error: "timeout"},
	}
	var buf bytes.Buffer
	writePingResults(&buf, results, false)
	output := buf.String()
	for _, want := range []string{"first: pong", "2.500ms", "sdk=0.0.17", "offline: failed: timeout"} {
		if !strings.Contains(output, want) {
			t.Fatalf("output missing %q: %s", want, output)
		}
	}
}
