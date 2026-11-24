package cli

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
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
func healthcheckTestBroker(t *testing.T, jetstream bool, extraArgs ...string) (string, *natsio.Conn, func()) {
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
	server := exec.Command(binary, append(args, extraArgs...)...)
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
			if jetstream {
				provisionPUDAResources(t, nc)
			}
			return url, nc, stop
		}
	}
	stop()
	t.Fatalf("loopback broker did not become ready: %s", log.String())
	return "", nil, nil
}

// provisionPUDAResources creates the required PUDA streams and KV buckets with
// one replica, as setup_streams.sh does on a single-node deployment. A broker
// whose account cannot create them is left as is.
func provisionPUDAResources(t *testing.T, nc *natsio.Conn) {
	t.Helper()
	js, err := nc.JetStream()
	if err != nil {
		return
	}
	for _, name := range []string{"COMMAND_QUEUE", "RESPONSE_QUEUE", "RESPONSE_IMMEDIATE"} {
		subject := "puda.*.cmd." + strings.ToLower(strings.TrimPrefix(strings.TrimPrefix(name, "COMMAND_"), "RESPONSE_"))
		if strings.HasPrefix(name, "RESPONSE_") {
			subject = "puda.*.cmd.response." + strings.ToLower(strings.TrimPrefix(name, "RESPONSE_"))
		}
		if _, err := js.AddStream(&natsio.StreamConfig{Name: name, Subjects: []string{subject}, Storage: natsio.MemoryStorage}); err != nil {
			return
		}
	}
	for _, bucket := range []string{"MACHINE_STATE", "MACHINE_COMMANDS"} {
		if _, err := js.CreateKeyValue(&natsio.KeyValueConfig{Bucket: bucket, Storage: natsio.MemoryStorage}); err != nil {
			return
		}
	}
}

// healthcheckRestrictedBroker starts a broker whose only user is denied one subject.
func healthcheckRestrictedBroker(t *testing.T, operation, subject string) string {
	t.Helper()
	config := fmt.Sprintf(`no_auth_user: probe
authorization {
  users: [{user: probe, permissions: {%s: {deny: [%q]}}}]
}`, operation, subject)
	path := filepath.Join(t.TempDir(), "restricted.conf")
	if err := os.WriteFile(path, []byte(config), 0600); err != nil {
		t.Fatal(err)
	}
	url, _, _ := healthcheckTestBroker(t, true, "-c", path)
	return url
}

func healthcheckTestConfig(t *testing.T, servers, gateways string) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_CONFIG_HOME", home)
	t.Setenv("AppData", home)
	t.Setenv("PUDA_NATS_CA", "")
	t.Setenv("PUDA_E2E_KEY_FILE", "")
	t.Setenv("PUDA_NO_UPDATE_NOTIFIER", "1")
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

// runHealthcheckInProcess runs the command handler and returns its JSON report.
func runHealthcheckInProcess(t *testing.T) (pudanats.HealthReport, string, error) {
	t.Helper()
	var out, stderr bytes.Buffer
	cmd := &cobra.Command{}
	cmd.SetOut(&out)
	cmd.SetErr(&stderr)
	err := runHealthcheck(cmd, nil)
	var report pudanats.HealthReport
	if !healthcheckHuman {
		if jsonErr := json.Unmarshal(out.Bytes(), &report); jsonErr != nil {
			t.Fatalf("JSON stdout: %v: %s", jsonErr, out.String())
		}
	}
	if stderr.Len() != 0 {
		t.Fatalf("unexpected stderr: %s", stderr.String())
	}
	return report, out.String(), err
}

// Execute the real command entry point in a fresh process; never share Cobra state.
func TestHealthcheckCommandProcess(t *testing.T) {
	if os.Getenv("PUDA_HEALTHCHECK_TEST_PROCESS") != "1" {
		return
	}
	Version = "0.1.6"
	for i, arg := range os.Args {
		if arg == "--" {
			rootCmd.SetArgs(os.Args[i+1:])
			break
		}
	}
	if err := Execute(); err != nil {
		os.Exit(1)
	}
	os.Exit(0)
}

func healthcheckProcess(t *testing.T, args ...string) *exec.Cmd {
	t.Helper()
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(binary, append([]string{"-test.run=^TestHealthcheckCommandProcess$", "--"}, args...)...)
	cmd.Env = append(os.Environ(), "PUDA_HEALTHCHECK_TEST_PROCESS=1")
	cmd.Dir = t.TempDir()
	return cmd
}

// runHealthcheckProcess runs the real binary and requires exactly one JSON report,
// empty stderr, and the given exit code.
func runHealthcheckProcess(t *testing.T, wantExit int) pudanats.HealthReport {
	t.Helper()
	cmd := healthcheckProcess(t, "healthcheck", "--timeout=200ms")
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	err := cmd.Run()
	exit := 0
	if exitErr, ok := err.(*exec.ExitError); ok {
		exit = exitErr.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	if exit != wantExit {
		t.Fatalf("exit=%d want=%d stdout=%s stderr=%s", exit, wantExit, stdout.String(), stderr.String())
	}
	if stderr.Len() != 0 {
		t.Fatalf("report must be complete without stderr: %s", stderr.String())
	}
	var report pudanats.HealthReport
	decoder := json.NewDecoder(&stdout)
	if err := decoder.Decode(&report); err != nil {
		t.Fatal(err)
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		t.Fatalf("not exactly one JSON report: %v", err)
	}
	return report
}

// A NATS INFO followed by TLS with an untrusted certificate reproduces unknown-CA.
func healthcheckUnknownCA(t *testing.T) string {
	t.Helper()
	certServer := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	cert := certServer.TLS.Certificates[0]
	certServer.Close()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() {
				defer conn.Close()
				conn.SetDeadline(time.Now().Add(time.Second))
				io.WriteString(conn, "INFO {\"server_id\":\"fixture\",\"tls_required\":true}\r\n")
				tls.Server(conn, &tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS12}).Handshake()
			}()
		}
	}()
	return "tls://" + listener.Addr().String()
}

// healthcheckTrustUnrelatedCA configures a valid CA that did not sign the server certificate.
func healthcheckTrustUnrelatedCA(t *testing.T) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	ca := &x509.Certificate{SerialNumber: big.NewInt(1), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour)}
	der, err := x509.CreateCertificate(rand.Reader, ca, ca, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	caPath := filepath.Join(os.Getenv("HOME"), "unrelated-ca.pem")
	if err := os.WriteFile(caPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0600); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(os.Getenv("XDG_CONFIG_HOME"), "puda", "config.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cfg map[string]any
	if err := json.Unmarshal(data, &cfg); err != nil {
		t.Fatal(err)
	}
	cfg["profiles"].(map[string]any)["isolated"].(map[string]any)["ca"] = caPath
	if data, err = json.Marshal(cfg); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestHealthcheckProcessUnreachableIsOneJSONWithoutStderr(t *testing.T) {
	for _, transport := range []string{"refused", "unknown-ca"} {
		t.Run(transport, func(t *testing.T) {
			listener, err := net.Listen("tcp", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			url := "nats://" + listener.Addr().String()
			listener.Close()
			if transport == "unknown-ca" {
				url = healthcheckUnknownCA(t)
			}
			healthcheckTestConfig(t, url, "")
			if transport == "unknown-ca" {
				healthcheckTrustUnrelatedCA(t)
			}
			// A fresh cached update notice must not contaminate this machine report.
			state, _ := json.Marshal(map[string]any{"checked_for_update_at": time.Now(), "latest_version": "99.0.0"})
			if err := os.WriteFile(filepath.Join(os.Getenv("XDG_CONFIG_HOME"), "puda", "state.json"), state, 0600); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PUDA_NO_UPDATE_NOTIFIER", "")
			report := runHealthcheckProcess(t, 1)
			if report.Status != "unhealthy" || report.Cluster.Reachable != 0 || report.Compatibility == nil || report.Compatibility.Status != "not_checked" || report.Compatibility.Reason != "nats_unreachable" {
				t.Fatalf("report=%+v", report)
			}
			if report.JetStream.Status != "not_checked" || report.JetStream.Reason != "nats_unreachable" || report.JetStream.Error != "" {
				t.Fatalf("dependent=%+v", report.JetStream)
			}
			if transport == "unknown-ca" && !strings.Contains(report.Servers[0].Error, "unknown authority") {
				t.Fatalf("lost TLS root cause: %+v", report.Servers)
			}
			data, _ := json.Marshal(report)
			root, _ := json.Marshal(report.Servers[0].Error)
			if report.Servers[0].Error == "" || bytes.Count(data, root) != 1 {
				t.Fatalf("root error must occur exactly once: %s", data)
			}
		})
	}
}

// Denied discovery is advisory: NATS stays healthy and the cause is structured.
func TestHealthcheckProcessDiscoveryPermissionDenied(t *testing.T) {
	for _, tc := range []struct{ operation, subject, diagnostic string }{
		{"publish", "puda.cmd.ping", `Publish to "puda.cmd.ping"`},
		// JetStream's request mux uses _INBOX.<id>.*, while fleet discovery
		// subscribes to an exact _INBOX.<id>. Deny only the latter.
		{"subscribe", "_INBOX.*", `Subscription to "_INBOX.`},
	} {
		t.Run(tc.operation, func(t *testing.T) {
			healthcheckTestConfig(t, healthcheckRestrictedBroker(t, tc.operation, tc.subject), "")
			report := runHealthcheckProcess(t, 0)
			if report.Status != "ok" || !report.JetStream.OK {
				t.Fatalf("discovery denial changed NATS health: %+v", report)
			}
			result := report.Compatibility
			if result == nil || result.Status != "not_checked" || result.Reason != "discovery_error" || !strings.Contains(result.Error, tc.diagnostic) {
				t.Fatalf("lost discovery permission cause: %+v", result)
			}
		})
	}
}

// Denied JetStream API access is reported in jetstream.error, not leaked to stderr.
func TestHealthcheckProcessJetStreamPermissionDenied(t *testing.T) {
	for _, tc := range []struct{ name, operation, subject, diagnostic string }{
		{"publish-api", "publish", "$JS.API.INFO", `Publish to "$JS.API.INFO"`},
		// The JetStream request mux subscribes _INBOX.<id>.*; discovery's
		// exact _INBOX.<id> remains allowed.
		{"subscribe-reply", "subscribe", "_INBOX.*.*", `Subscription to "_INBOX.`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			healthcheckTestConfig(t, healthcheckRestrictedBroker(t, tc.operation, tc.subject), "")
			report := runHealthcheckProcess(t, 1)
			js := report.JetStream
			if report.Status != "unhealthy" || js.Status != "failed" || js.Reason != "jetstream_error" || !strings.Contains(js.Error, tc.diagnostic) {
				t.Fatalf("lost JetStream permission cause: %+v", report)
			}
		})
	}
}

func TestHealthcheckProcessOperationalErrorsStillVisible(t *testing.T) {
	for _, scenario := range []string{"unrelated-command", "output-failure", "config-failure"} {
		t.Run(scenario, func(t *testing.T) {
			healthcheckTestConfig(t, "nats://127.0.0.1:1", "")
			args := []string{"healthcheck", "--timeout=50ms"}
			if scenario == "unrelated-command" {
				args = []string{"not-a-command"}
			}
			if scenario == "config-failure" {
				if err := os.WriteFile(filepath.Join(os.Getenv("XDG_CONFIG_HOME"), "puda", "config.json"), []byte("bad json"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			cmd := healthcheckProcess(t, args...)
			var stdout, stderr bytes.Buffer
			cmd.Stdout, cmd.Stderr = &stdout, &stderr
			if scenario == "output-failure" {
				full, err := os.OpenFile("/dev/full", os.O_WRONLY, 0)
				if err != nil {
					t.Skip("/dev/full unavailable")
				}
				defer full.Close()
				cmd.Stdout = full
			}
			if err := cmd.Run(); err == nil {
				t.Fatal("expected nonzero exit")
			}
			if !strings.Contains(stderr.String(), "Error:") || strings.Contains(stderr.String(), "Error: NATS healthcheck") {
				t.Fatalf("wrong operational error: %s", stderr.String())
			}
			if stdout.Len() != 0 {
				t.Fatalf("unexpected stdout: %s", stdout.String())
			}
		})
	}
}

// A subscriber that never replies must not be mistaken for a responding edge.
func TestHealthcheckSilentSubscriberIsNoResponders(t *testing.T) {
	url, nc, _ := healthcheckTestBroker(t, true)
	healthcheckTestConfig(t, url, "")
	if _, err := nc.Subscribe("puda.cmd.ping", func(*natsio.Msg) {}); err != nil {
		t.Fatal(err)
	}
	if err := nc.Flush(); err != nil {
		t.Fatal(err)
	}
	report, _, err := runHealthcheckInProcess(t)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != pudanats.HealthOK || report.Compatibility.Status != "not_checked" || report.Compatibility.Reason != "no_responders" {
		t.Fatalf("report=%+v compatibility=%+v", report, report.Compatibility)
	}
}

func TestHealthcheckOfflineTimeoutIsBounded(t *testing.T) {
	// Accept TCP handshakes but never send NATS INFO, forcing the dial deadline.
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	healthcheckTestConfig(t, "nats://"+listener.Addr().String(), "")
	started := time.Now()
	report, _, err := runHealthcheckInProcess(t)
	if err == nil || err.Error() != "NATS healthcheck unhealthy" {
		t.Fatalf("error=%v", err)
	}
	if elapsed := time.Since(started); elapsed > 2*time.Second {
		t.Fatalf("unbounded offline check: %s", elapsed)
	}
	if report.Status != pudanats.HealthUnhealthy || report.Compatibility.Reason != "nats_unreachable" {
		t.Fatalf("report=%+v", report)
	}
}

// A mismatched SDK never changes NATS status or exit error, in JSON or human output.
func TestHealthcheckStatusRemainsNATSOnly(t *testing.T) {
	for _, tc := range []struct {
		name                                    string
		jetstream, offlineLocal, offlineGateway bool
		status                                  string
	}{
		{name: "healthy", jetstream: true, status: pudanats.HealthOK},
		{name: "degraded-local", jetstream: true, offlineLocal: true, status: pudanats.HealthDegraded},
		{name: "unhealthy-jetstream", status: pudanats.HealthUnhealthy},
		{name: "degraded-gateway", jetstream: true, offlineGateway: true, status: pudanats.HealthDegraded},
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
				healthcheckHuman = human
				report, out, err := runHealthcheckInProcess(t)
				if tc.status == pudanats.HealthOK && err != nil {
					t.Fatal(err)
				}
				if tc.status != pudanats.HealthOK && (err == nil || err.Error() != "NATS healthcheck "+tc.status) {
					t.Fatalf("error=%v want status=%s", err, tc.status)
				}
				if human {
					if !strings.Contains(out, "status: "+tc.status) || !strings.Contains(out, "compatibility: unsupported") {
						t.Fatalf("human output=%s", out)
					}
					continue
				}
				wantJS := "ok"
				if !tc.jetstream {
					wantJS = "failed"
				}
				if report.Status != tc.status || report.JetStream.Status != wantJS || report.Compatibility.Status != "unsupported" {
					t.Fatalf("report=%s", out)
				}
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
	report, out, err := runHealthcheckInProcess(t)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != pudanats.HealthOK || report.Compatibility.Status != "not_checked" || report.Compatibility.Reason != "discovery_error" {
		t.Fatalf("missing structured discovery error: %s", out)
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
	// Multiple independent subscriptions prove discovery does not stop at the first pong;
	// each replies twice to prove responders are deduplicated.
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
	kv, err := js.KeyValue("MACHINE_STATE")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := kv.Put("stale-offline", []byte(`{"sdk_version":"99.0.0","state":"idle"}`)); err != nil {
		t.Fatal(err)
	}
	if err := nc.Flush(); err != nil {
		t.Fatal(err)
	}
	report, out, err := runHealthcheckInProcess(t)
	if err != nil {
		t.Fatal(err)
	}
	result := report.Compatibility
	if report.Status != pudanats.HealthOK || len(result.Machines) != len(results) || result.CLIVersion != Version || result.Status != "unsupported" {
		t.Fatalf("missing structured fleet evaluation: %s", out)
	}
	byID := make(map[string]compatibility.Status)
	for _, edge := range result.Machines {
		byID[edge.MachineID] = edge.Status
		if len(edge.SupportedRanges) == 0 {
			t.Errorf("missing declared ranges: %+v", edge)
		}
	}
	for _, edge := range results {
		want := compatibility.Bundled().Evaluate(Version, edge.SDKVersion).Status
		if byID[edge.MachineID] != want {
			t.Errorf("%s: got=%s want=%s", edge.MachineID, byID[edge.MachineID], want)
		}
	}
	if strings.Contains(out, "stale-offline") {
		t.Fatal("consulted stale stored state")
	}
}

// A broker with JetStream but without the PUDA resources answers every NATS
// probe, yet no command can be queued: the report must be unhealthy and the
// issue must carry the provisioning command.
func TestHealthcheckProcessMissingPUDAResourceIsUnhealthy(t *testing.T) {
	url, nc, _ := healthcheckTestBroker(t, true)
	js, err := nc.JetStream()
	if err != nil {
		t.Fatal(err)
	}
	if err := js.DeleteStream("COMMAND_QUEUE"); err != nil {
		t.Fatal(err)
	}
	healthcheckTestConfig(t, url, "")
	report := runHealthcheckProcess(t, 1)
	if report.Status != "unhealthy" || !report.JetStream.OK || report.PUDA.Status != "failed" {
		t.Fatalf("status=%s jetstream=%+v puda=%+v", report.Status, report.JetStream, report.PUDA)
	}
	if len(report.Issues) != 1 || report.Issues[0].Code != "puda_resources_missing" || report.Issues[0].Target != "COMMAND_QUEUE" || !strings.Contains(report.Issues[0].NextStep, "NATS_URL="+url+" REPLICAS=1") {
		t.Fatalf("issues=%+v", report.Issues)
	}
	if len(report.Cluster.Brokers) != 1 || report.Cluster.Brokers[0].Endpoints[0] != url {
		t.Fatalf("brokers=%+v", report.Cluster.Brokers)
	}
}

// A healthy provisioned standalone broker has an empty, non-null issue list.
func TestHealthcheckProcessHealthyHasEmptyIssues(t *testing.T) {
	url, _, _ := healthcheckTestBroker(t, true)
	healthcheckTestConfig(t, url, "")
	cmd := healthcheckProcess(t, "healthcheck", "--timeout=2s")
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	if err := cmd.Run(); err != nil {
		t.Fatalf("err=%v stdout=%s", err, stdout.String())
	}
	if !bytes.Contains(stdout.Bytes(), []byte(`"issues": []`)) || !bytes.Contains(stdout.Bytes(), []byte(`"status": "ok"`)) {
		t.Fatalf("stdout=%s", stdout.String())
	}
}
