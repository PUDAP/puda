package cli

import (
	"bytes"
	"errors"
	"io"
	"testing"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/spf13/cobra"
)

func TestDiscoveryCompatibilityPreservesOutput(t *testing.T) {
	for _, list := range []bool{true, false} {
		for _, human := range []bool{true, false} {
			results := []pudanats.PingResult{
				{MachineID: "current", Status: "pong", SDKVersion: "0.1.0", ProtocolVersion: "1.0"},
				{MachineID: "legacy", Status: "pong", SDKVersion: "0.0.23"},
				{MachineID: "future", Status: "pong", ProtocolVersion: "2.0"},
			}
			var out, stderr, expected bytes.Buffer
			cmd := &cobra.Command{}
			cmd.SetOut(&out)
			cmd.SetErr(&stderr)
			if list {
				_ = writeListResults(&expected, results, nil, human)
			} else {
				_ = writeInfoResults(&expected, results, nil, human)
			}
			if err := writeMachineDiscovery(cmd, results, nil, human, list); err != nil {
				t.Fatal(err)
			}
			if out.String() != expected.String() {
				t.Fatalf("output changed: %s", out.String())
			}
			want := "warning: machine legacy speaks edge protocol none; this CLI supports 1.x (update the edge's PUDA SDK)\n" +
				"warning: machine future speaks edge protocol 2.0; this CLI supports 1.x (update the edge's PUDA SDK)\n"
			if stderr.String() != want {
				t.Fatalf("stderr warnings: %q", stderr.String())
			}
		}
	}
}

func TestDiscoveryNoPongNoCompatibilityWarning(t *testing.T) {
	for _, results := range [][]pudanats.PingResult{nil, {{MachineID: "offline", Status: "timeout"}}} {
		var stderr bytes.Buffer
		cmd := &cobra.Command{}
		cmd.SetOut(io.Discard)
		cmd.SetErr(&stderr)
		if err := writeMachineDiscovery(cmd, results, nil, false, false); err != nil {
			t.Fatal(err)
		}
		if stderr.Len() != 0 {
			t.Fatalf("false warning: %s", stderr.String())
		}
	}
}

type failedDiscoveryWriter struct{}

func (failedDiscoveryWriter) Write(p []byte) (int, error) { return 0, errors.New("write failed") }

func TestDiscoveryWarningFailureIsNonblocking(t *testing.T) {
	cmd := &cobra.Command{}
	cmd.SetOut(io.Discard)
	cmd.SetErr(failedDiscoveryWriter{})
	if err := writeMachineDiscovery(cmd, []pudanats.PingResult{{MachineID: "edge", Status: "pong"}}, nil, false, false); err != nil {
		t.Fatal(err)
	}
}

func TestDiscoveryOutputFailureIsPreserved(t *testing.T) {
	cmd := &cobra.Command{}
	var stderr bytes.Buffer
	cmd.SetOut(failedDiscoveryWriter{})
	cmd.SetErr(&stderr)
	if err := writeMachineDiscovery(cmd, []pudanats.PingResult{{MachineID: "edge", Status: "pong"}}, nil, false, true); err == nil {
		t.Fatal("lost output failure")
	}
	if stderr.Len() != 0 {
		t.Fatal("warned on unsuccessful output")
	}
}
