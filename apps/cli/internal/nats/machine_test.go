package nats

import "testing"

func TestParsePong(t *testing.T) {
	pong, ok := parsePong([]byte(`{"status":"pong","machine_id":"test-1","timestamp":"2026-08-27T07:23:56Z","sdk_version":"0.0.17","uptime_seconds":12.5}`))
	if !ok {
		t.Fatal("valid pong rejected")
	}
	if pong.MachineID != "test-1" || pong.SDKVersion != "0.0.17" || pong.UptimeSeconds != 12.5 {
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
