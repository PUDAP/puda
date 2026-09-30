package nats

import (
	"strings"
	"testing"
)

func TestParsePong(t *testing.T) {
	pong, ok := parsePong([]byte(`{"status":"pong","machine_id":"test-1","timestamp":"2026-08-27T07:23:56Z","sdk_version":"0.0.17","uptime_seconds":12.5,"run_status":"busy","description":"Software-only test machine.","local_ip":"192.168.1.10","tailscale_ip":"100.99.243.61","magicdns":"host.tailnet.ts.net"}`))
	if !ok {
		t.Fatal("valid pong rejected")
	}
	if pong.MachineID != "test-1" || pong.SDKVersion != "0.0.17" || pong.UptimeSeconds != 12.5 || pong.RunStatus != "busy" || pong.Description != "Software-only test machine." || pong.LocalIP != "192.168.1.10" || pong.TailscaleIP != "100.99.243.61" || pong.MagicDNS != "host.tailnet.ts.net" {
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

func TestParseMachineCommandsPreservesParameterSchemas(t *testing.T) {
	payload := []byte(`{
		"commands":"load_deck(self, layout: Dict[str, str])",
		"catalog":[{
			"name":"load_deck",
			"signature":"(self, layout: Dict[str, str]) -> dict",
			"doc":"Load the deck.",
			"safety":null,
			"parameters":{"layout":{"required":true,"schema":{"kind":"dict","values":{"kind":"str"}}}}
		}]
	}`)
	commands, err := parseMachineCommands(payload)
	if err != nil {
		t.Fatal(err)
	}
	entry := commands.Catalog[0]
	if entry.Parameters == nil || len(entry.Parameters["layout"].Schema) == 0 {
		t.Fatalf("parameters = %+v", entry.Parameters)
	}
	if string(entry.Parameters["layout"].Schema) != `{"kind":"dict","values":{"kind":"str"}}` {
		t.Fatalf("schema = %s", entry.Parameters["layout"].Schema)
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

func TestWatchSubjectsDefaultsAndMachines(t *testing.T) {
	got, err := WatchSubjects(nil, nil)
	if err != nil || strings.Join(got, ",") != "puda.*.>" {
		t.Fatalf("got=%v err=%v", got, err)
	}
	got, err = WatchSubjects([]string{"first", "lab.second", "first"}, nil)
	if err != nil || strings.Join(got, ",") != "puda.first.>,puda.lab-second.>" {
		t.Fatalf("got=%v err=%v", got, err)
	}
}

func TestWatchSubjectsAcceptsFullSubjects(t *testing.T) {
	in := []string{"puda.balance.tlm.stream.weight", "puda.*.tlm.stream.>", "puda.>"}
	got, err := WatchSubjects(nil, in)
	if err != nil || strings.Join(got, ",") != strings.Join(in, ",") {
		t.Fatalf("got=%v err=%v", got, err)
	}
}

func TestWatchSubjectsRejectsInvalid(t *testing.T) {
	for _, subject := range []string{
		"tlm.stream.pos",
		"puda",
		"puda..tlm",
		"puda.first.>.pos",
		"puda.fir*.tlm",
		"puda.first tlm",
	} {
		if _, err := WatchSubjects(nil, []string{subject}); err == nil {
			t.Fatalf("expected error for %q", subject)
		}
	}
	if _, err := WatchSubjects([]string{"first"}, []string{"puda.first.>"}); err == nil {
		t.Fatal("expected error when combining subjects and machines")
	}
}

func TestSubjectsNameHeartbeat(t *testing.T) {
	if !subjectsNameHeartbeat([]string{"puda.first.tlm.heartbeat"}) || !subjectsNameHeartbeat([]string{"puda.*.tlm.heartbeat"}) {
		t.Fatal("explicit heartbeat subject must include heartbeats")
	}
	if subjectsNameHeartbeat([]string{"puda.*.>", "puda.first.tlm.>"}) {
		t.Fatal("wildcard subjects must not include heartbeats")
	}
}
