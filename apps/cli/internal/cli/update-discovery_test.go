package cli

import (
	"bytes"
	"net"
	"strings"
	"testing"
	"time"

	compatibility "github.com/PUDAP/puda"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
)

func TestUpdateFleetNoRespondersIsNotApproval(t *testing.T) {
	url, _, _ := healthcheckTestBroker(t, true)
	healthcheckTestConfig(t, url, "")
	var out bytes.Buffer
	writeFleetCompatibility(&out, url, 30*time.Millisecond, "0.1.6", compatibility.Bundled(), "0.1.5")
	if !strings.Contains(out.String(), "no edges responded") || !strings.Contains(out.String(), "not checked") || strings.Contains(out.String(), "Warning: machine") {
		t.Fatal(out.String())
	}
}

func TestUpdateFleetConnectionTimeoutIsNotApproval(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	var out bytes.Buffer
	started := time.Now()
	writeFleetCompatibility(&out, "nats://"+listener.Addr().String(), 30*time.Millisecond, "0.1.6", compatibility.Bundled(), "0.1.5")
	if time.Since(started) > time.Second {
		t.Fatal("connection timeout was not bounded")
	}
	if !strings.Contains(out.String(), "not checked") || !strings.Contains(out.String(), "discovery unavailable") || strings.Contains(out.String(), "Warning: machine") {
		t.Fatal(out.String())
	}
}

func TestUpdateUnknownCurrentDoesNotClaimNewMismatch(t *testing.T) {
	var out bytes.Buffer
	target, err := compatibility.Parse([]byte(`{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.99","max":"0.0.99"}}]}`))
	if err != nil {
		t.Fatal(err)
	}
	writeCompatibilityWarnings(&out, []pudanats.PingResult{{MachineID: "oven", Status: "pong", SDKVersion: "0.0.21"}}, "0.1.6", target, "dev")
	if !strings.Contains(out.String(), "current compatibility unknown") || strings.Contains(out.String(), "newly unsupported") {
		t.Fatal(out.String())
	}
}
