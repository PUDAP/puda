package nats

import (
	"strings"
	"testing"
)

func TestParsePong(t *testing.T) {
	pong, ok := parsePong([]byte(`{"status":"pong","machine_id":"test-1","timestamp":"2026-08-27T07:23:56Z","sdk_version":"0.0.17","uptime_seconds":12.5,"run_status":"busy","description":"Software-only test machine."}`))
	if !ok {
		t.Fatal("valid pong rejected")
	}
	if pong.MachineID != "test-1" || pong.SDKVersion != "0.0.17" || pong.UptimeSeconds != 12.5 || pong.RunStatus != "busy" || pong.Description != "Software-only test machine." {
		t.Fatalf("pong=%+v", pong)
	}
}

func TestMachineIDFromPong(t *testing.T) {
	id, ok := machineIDFromPong([]byte(`{"status":"pong","machine_id":"test-1"}`))
	if !ok || id != "test-1" {
		t.Fatalf("id=%q ok=%v", id, ok)
	}
}

func TestMachineIDFromPongRejectsInvalidResponses(t *testing.T) {
	for _, payload := range [][]byte{
		[]byte(`{"status":"error","machine_id":"test-1"}`),
		[]byte(`{"status":"pong","machine_id":""}`),
		[]byte(`not-json`),
	} {
		if id, ok := machineIDFromPong(payload); ok {
			t.Fatalf("accepted %q as %q", payload, id)
		}
	}
}

func TestParseMachineCommandsPreservesStructuredCatalog(t *testing.T) {
	payload := []byte(`{
		"commands":"run(self, value: int)",
		"catalog":[{
			"name":"run",
			"signature":"(value: int) -> None",
			"doc":"Run once.",
			"safety":{"summary":"Take care.","hazards":["motion"],"requires":null,"forbidden_when":"door open","confirm":false}
		}]
	}`)
	commands, err := parseMachineCommands(payload)
	if err != nil {
		t.Fatal(err)
	}
	if commands.Commands == "" || len(commands.Catalog) != 1 {
		t.Fatalf("commands = %+v", commands)
	}
	entry := commands.Catalog[0]
	if entry.Doc == nil || *entry.Doc != "Run once." || !entry.SafetyPresent || entry.Safety == nil {
		t.Fatalf("entry = %+v", entry)
	}
	if entry.Safety.Confirm == nil || *entry.Safety.Confirm {
		t.Fatalf("confirm = %v", entry.Safety.Confirm)
	}
}

func TestParseMachineCommandsRejectsMissingCatalogFields(t *testing.T) {
	payloads := []string{
		`{"commands":"run()"}`,
		`{"commands":"run()","catalog":[{"signature":"()","doc":null,"safety":null}]}`,
		`{"commands":"run()","catalog":[{"name":"run","doc":null,"safety":null}]}`,
		`{"commands":"run()","catalog":[{"name":"run","signature":"()","safety":null}]}`,
		`{"commands":"run()","catalog":[{"name":"run","signature":"()","doc":null}]}`,
		`{"commands":"run()","catalog":[{"name":"run","signature":"()","doc":null,"safety":{"summary":"safe","hazards":[],"requires":null,"forbidden_when":null}}]}`,
	}
	for _, payload := range payloads {
		if _, err := parseMachineCommands([]byte(payload)); err == nil || !strings.Contains(err.Error(), "catalog") {
			t.Fatalf("payload %s: error = %v", payload, err)
		}
	}
}
