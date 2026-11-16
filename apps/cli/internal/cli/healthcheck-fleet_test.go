package cli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	compatibility "github.com/PUDAP/puda"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

// These integration tests only use a disposable loopback broker and config.
// Set PUDA_TEST_NATS_SERVER or install nats-server on PATH to enable them.
func healthcheckTestBroker(t *testing.T, jetstream bool) (string, *natsio.Conn, func()) {
	t.Helper()
	binary := os.Getenv("PUDA_TEST_NATS_SERVER")
	if binary == "" {
		var err error
		binary, err = exec.LookPath("nats-server")
		if err != nil {
			t.Skip("set PUDA_TEST_NATS_SERVER to run loopback healthcheck integration tests")
		}
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	args := []string{"-a", "127.0.0.1", "-p", fmt.Sprint(port)}
	if jetstream {
		args = append(args, "-js", "-sd", t.TempDir())
	}
	server := exec.Command(binary, args...)
	var log bytes.Buffer
	server.Stdout, server.Stderr = &log, &log
	if err := server.Start(); err != nil {
		t.Fatal(err)
	}
	var once sync.Once
	stop := func() { once.Do(func() { _ = server.Process.Kill(); _ = server.Wait() }) }
	t.Cleanup(stop)
	url := fmt.Sprintf("nats://127.0.0.1:%d", port)
	for deadline := time.Now().Add(5 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		nc, err := natsio.Connect(url, natsio.Timeout(50*time.Millisecond), natsio.NoReconnect())
		if err == nil {
			t.Cleanup(nc.Close)
			return url, nc, stop
		}
	}
	t.Fatal("loopback broker did not become ready")
	return "", nil, nil
}

func healthcheckTestConfig(t *testing.T, servers, gateways string) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_CONFIG_HOME", home)
	t.Setenv("AppData", home)
	t.Setenv("PUDA_NATS_CA", "")
	t.Setenv("PUDA_E2E_KEY_FILE", "")
	config := map[string]any{
		"user":           map[string]string{"username": "test", "user_id": "test"},
		"active_profile": "isolated",
		"profiles":       map[string]any{"isolated": map[string]any{"nats_servers": servers, "gateway_servers": gateways, "e2e": false}},
	}
	data, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(home, "puda")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "config.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	oldTimeout, oldHuman, oldVersion := healthcheckTimeout, healthcheckHuman, Version
	healthcheckTimeout, healthcheckHuman, Version = 100*time.Millisecond, false, "0.1.6"
	t.Cleanup(func() {
		healthcheckTimeout, healthcheckHuman, Version = oldTimeout, oldHuman, oldVersion
		pudanats.SetRing(nil)
	})
}

func TestHealthcheckNoRespondersReportsUnchecked(t *testing.T) {
	for _, silent := range []bool{false, true} {
		t.Run(fmt.Sprintf("silent-subscription=%t", silent), func(t *testing.T) {
			url, nc, _ := healthcheckTestBroker(t, true)
			healthcheckTestConfig(t, url, "")
			if silent {
				if _, err := nc.Subscribe("puda.cmd.ping", func(*natsio.Msg) {}); err != nil {
					t.Fatal(err)
				}
				if err := nc.Flush(); err != nil {
					t.Fatal(err)
				}
			}
			var out, stderr bytes.Buffer
			cmd := &cobra.Command{}
			cmd.SetOut(&out)
			cmd.SetErr(&stderr)
			started := time.Now()
			if err := runHealthcheck(cmd, nil); err != nil {
				t.Fatal(err)
			}
			if elapsed := time.Since(started); elapsed > 2*time.Second {
				t.Fatalf("unbounded discovery: %s", elapsed)
			}
			var report pudanats.HealthReport
			if err := json.Unmarshal(out.Bytes(), &report); err != nil {
				t.Fatal(err)
			}
			if report.Status != pudanats.HealthOK {
				t.Fatalf("status=%s", report.Status)
			}
			if !strings.Contains(stderr.String(), "no edges responded") || !strings.Contains(stderr.String(), "not checked") {
				t.Fatalf("missing unchecked diagnostic: %q", stderr.String())
			}
			if strings.Contains(stderr.String(), "Warning: machine") {
				t.Fatal("fabricated per-edge warning")
			}
		})
	}
}

func TestHealthcheckOfflineTimeoutPreservesFailure(t *testing.T) {
	// Accept TCP handshakes but never send NATS INFO, forcing the dial deadline.
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	healthcheckTestConfig(t, "nats://"+listener.Addr().String(), "")
	var out, stderr bytes.Buffer
	cmd := &cobra.Command{}
	cmd.SetOut(&out)
	cmd.SetErr(&stderr)
	started := time.Now()
	err = runHealthcheck(cmd, nil)
	if err == nil || err.Error() != "NATS healthcheck unhealthy" {
		t.Fatalf("error=%v", err)
	}
	if elapsed := time.Since(started); elapsed > 2*time.Second {
		t.Fatalf("unbounded offline check: %s", elapsed)
	}
	var report pudanats.HealthReport
	if err := json.Unmarshal(out.Bytes(), &report); err != nil {
		t.Fatal(err)
	}
	if report.Status != pudanats.HealthUnhealthy || report.Cluster.Reachable != 0 {
		t.Fatalf("report=%+v", report)
	}
	if !strings.Contains(stderr.String(), "compatibility not checked") || !strings.Contains(stderr.String(), "discovery unavailable") {
		t.Fatalf("missing discovery diagnostic: %q", stderr.String())
	}
	if strings.Contains(stderr.String(), "Warning: machine") {
		t.Fatal("fabricated per-edge warning")
	}
}

func TestHealthcheckStatusAndOutputRemainNATSOnly(t *testing.T) {
	for _, tc := range []struct {
		name                                    string
		jetstream, offlineLocal, offlineGateway bool
		status                                  string
	}{
		{name: "healthy", jetstream: true, status: pudanats.HealthOK},
		{name: "degraded-local", jetstream: true, offlineLocal: true, status: pudanats.HealthDegraded},
		{name: "unhealthy-jetstream", status: pudanats.HealthUnhealthy},
		{name: "unhealthy-gateway", jetstream: true, offlineGateway: true, status: pudanats.HealthDegraded},
	} {
		t.Run(tc.name, func(t *testing.T) {
			url, nc, _ := healthcheckTestBroker(t, tc.jetstream)
			listener, err := net.Listen("tcp", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			offline := "nats://" + listener.Addr().String()
			listener.Close()
			servers, gateways := url, ""
			if tc.offlineLocal {
				servers += "," + offline
			}
			if tc.offlineGateway {
				gateways = offline
			}
			healthcheckTestConfig(t, servers, gateways)
			if _, err := nc.Subscribe("puda.cmd.ping", func(msg *natsio.Msg) {
				_ = msg.Respond([]byte(`{"machine_id":"responding","status":"pong","sdk_version":"99.0.0"}`))
			}); err != nil {
				t.Fatal(err)
			}
			if err := nc.Flush(); err != nil {
				t.Fatal(err)
			}
			for _, human := range []bool{false, true} {
				for _, brokenStderr := range []bool{false, true} {
					healthcheckHuman = human
					var out, stderr bytes.Buffer
					cmd := &cobra.Command{}
					cmd.SetOut(&out)
					cmd.SetErr(&stderr)
					if brokenStderr {
						cmd.SetErr(failedDiscoveryWriter{})
					}
					err := runHealthcheck(cmd, nil)
					if tc.status == pudanats.HealthOK && err != nil {
						t.Fatal(err)
					}
					if tc.status != pudanats.HealthOK && (err == nil || err.Error() != "NATS healthcheck "+tc.status) {
						t.Fatalf("error=%v want status=%s", err, tc.status)
					}
					if human {
						if !strings.Contains(out.String(), "status: "+tc.status) || strings.Contains(out.String(), "Python SDK") {
							t.Fatalf("human output=%s", out.String())
						}
					} else {
						var report pudanats.HealthReport
						if err := json.Unmarshal(out.Bytes(), &report); err != nil {
							t.Fatal(err)
						}
						if report.Status != tc.status {
							t.Fatalf("status=%s", report.Status)
						}
						var fields map[string]json.RawMessage
						if err := json.Unmarshal(out.Bytes(), &fields); err != nil {
							t.Fatal(err)
						}
						if len(fields) != 5 {
							t.Fatalf("health schema changed: %s", out.String())
						}
					}
					if !brokenStderr && stderr.String() != compatibility.PythonSDKWarning(Version, "responding", "99.0.0") {
						t.Fatalf("stderr=%q", stderr.String())
					}
				}
			}
			healthcheckHuman = false // Existing JSON writer propagates stdout failures.
			cmd := &cobra.Command{}
			var stderr bytes.Buffer
			cmd.SetOut(failedDiscoveryWriter{})
			cmd.SetErr(&stderr)
			if err := runHealthcheck(cmd, nil); err == nil || !strings.Contains(err.Error(), "write failed") {
				t.Fatalf("lost stdout error: %v", err)
			}
			if stderr.Len() != 0 {
				t.Fatalf("advised after output failed: %s", stderr.String())
			}
		})
	}
}

func TestHealthcheckDiscoveryDisconnectIsAdvisory(t *testing.T) {
	url, nc, stop := healthcheckTestBroker(t, true)
	healthcheckTestConfig(t, url, "")
	if _, err := nc.Subscribe("puda.cmd.ping", func(*natsio.Msg) { stop() }); err != nil {
		t.Fatal(err)
	}
	if err := nc.Flush(); err != nil {
		t.Fatal(err)
	}
	var out, stderr bytes.Buffer
	cmd := &cobra.Command{}
	cmd.SetOut(&out)
	cmd.SetErr(&stderr)
	if err := runHealthcheck(cmd, nil); err != nil {
		t.Fatal(err)
	}
	var report pudanats.HealthReport
	if err := json.Unmarshal(out.Bytes(), &report); err != nil {
		t.Fatal(err)
	}
	if report.Status != pudanats.HealthOK {
		t.Fatalf("discovery changed status: %s", report.Status)
	}
	if !strings.Contains(stderr.String(), "compatibility not checked") || !strings.Contains(stderr.String(), "discovery unavailable") {
		t.Fatalf("missing discovery error: %q", stderr.String())
	}
}

func TestHealthcheckFleetAllResponders(t *testing.T) {
	url, nc, _ := healthcheckTestBroker(t, true)
	healthcheckTestConfig(t, url, "")
	results := []pudanats.PingResult{
		{MachineID: "stable", Status: "pong", SDKVersion: "0.0.22"},
		{MachineID: "unlisted", Status: "pong", SDKVersion: "99.0.0"},
		{MachineID: "missing", Status: "pong"},
		{MachineID: "development", Status: "pong", SDKVersion: "0.0.22.dev1"},
		{MachineID: "malformed", Status: "pong", SDKVersion: "not-a-version"},
	}
	// Multiple independent subscriptions prove discovery does not stop at the first pong.
	for _, result := range results {
		payload, err := json.Marshal(result)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := nc.Subscribe("puda.cmd.ping", func(msg *natsio.Msg) { _ = msg.Respond(payload); _ = msg.Respond(payload) }); err != nil {
			t.Fatal(err)
		}
	}
	// Stored state must neither add a stale edge nor constrain live discovery.
	js, err := nc.JetStream()
	if err != nil {
		t.Fatal(err)
	}
	kv, err := js.CreateKeyValue(&natsio.KeyValueConfig{Bucket: "MACHINE_STATE"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := kv.Put("stale-offline", []byte(`{"sdk_version":"99.0.0","state":"idle"}`)); err != nil {
		t.Fatal(err)
	}
	if err := nc.Flush(); err != nil {
		t.Fatal(err)
	}
	var stdout, stderr bytes.Buffer
	cmd := &cobra.Command{}
	cmd.SetOut(&stdout)
	cmd.SetErr(&stderr)
	if err := runHealthcheck(cmd, nil); err != nil {
		t.Fatal(err)
	}
	var report pudanats.HealthReport
	if err := json.Unmarshal(stdout.Bytes(), &report); err != nil {
		t.Fatalf("JSON stdout: %v: %s", err, stdout.String())
	}
	if report.Status != pudanats.HealthOK {
		t.Fatalf("status=%s", report.Status)
	}
	expectedWarnings := 0
	for _, result := range results {
		warning := compatibility.PythonSDKWarning(Version, result.MachineID, result.SDKVersion)
		if warning != "" {
			expectedWarnings++
			if strings.Count(stderr.String(), warning) != 1 {
				t.Errorf("expected one advisory %q, got %q", warning, stderr.String())
			}
		} else if strings.Contains(stderr.String(), fmt.Sprintf("machine %q", result.MachineID)) {
			t.Errorf("supported pair must be silent: %s", stderr.String())
		}
	}
	if strings.Count(stderr.String(), "Warning: machine") != expectedWarnings {
		t.Fatalf("unexpected advisory count: %s", stderr.String())
	}
	if strings.Contains(stderr.String(), "stale-offline") {
		t.Fatal("consulted stale stored state")
	}
}
