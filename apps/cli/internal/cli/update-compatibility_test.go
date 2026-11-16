package cli

import (
	"bytes"
	"context"
	"encoding/base64"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/spf13/cobra"

	compatibility "github.com/PUDAP/puda"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	natsio "github.com/nats-io/nats.go"
)

type preflightLocalTransport struct {
	base      *url.URL
	transport http.RoundTripper
}

func (r preflightLocalTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	clone := req.Clone(req.Context())
	u := *req.URL
	clone.URL = &u
	clone.URL.Scheme = r.base.Scheme
	clone.URL.Host = r.base.Host
	return r.transport.RoundTrip(clone)
}

func TestUpdateCommandTargetPolicyPreflight(t *testing.T) {
	urlBroker, nc, _ := healthcheckTestBroker(t, true)
	healthcheckTestConfig(t, urlBroker, "")
	_, err := nc.Subscribe("puda.cmd.ping", func(m *natsio.Msg) {
		_ = m.Respond([]byte(`{"machine_id":"kiln","status":"pong","sdk_version":"0.0.22"}`))
	})
	if err != nil {
		t.Fatal(err)
	}
	if err = nc.Flush(); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name, body string
		missing    bool
		want       string
	}{
		{name: "target-differs-from-bundled", body: `{"compatibility":[{"cli":{"min":"0.1.7","max":"0.1.7"},"python_sdk":{"min":"0.0.99","max":"0.0.99"}}]}`, want: "newly unsupported by target"},
		{name: "no-metadata", missing: true, want: "compatibility unknown"},
		{name: "no-target-entry", body: `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.22","max":"0.0.22"}}]}`, want: "compatibility unknown"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				switch {
				case strings.HasSuffix(r.URL.Path, "/releases/latest"):
					fmt.Fprint(w, `{"tag_name":"v0.1.7","assets":[]}`)
				case strings.HasSuffix(r.URL.Path, "/releases"):
					fmt.Fprint(w, `[]`)
				case strings.HasSuffix(r.URL.Path, "/git/ref/tags/v0.1.7"):
					fmt.Fprintf(w, `{"object":{"type":"commit","sha":%q}}`, strings.Repeat("a", 40))
				case strings.HasSuffix(r.URL.Path, "/contents/compatibility.json"):
					if tc.missing {
						http.NotFound(w, r)
						return
					}
					fmt.Fprintf(w, `{"encoding":"base64","content":%q}`, base64.StdEncoding.EncodeToString([]byte(tc.body)))
				default:
					t.Errorf("unexpected request %s", r.URL)
					http.NotFound(w, r)
				}
			}))
			defer server.Close()
			base, _ := url.Parse(server.URL)
			old := http.DefaultTransport
			http.DefaultTransport = preflightLocalTransport{base, old}
			defer func() { http.DefaultTransport = old }()
			oldYes, oldTarget := updateYes, updateTargetVersion
			updateYes, updateTargetVersion = true, ""
			defer func() { updateYes, updateTargetVersion = oldYes, oldTarget }()
			var out, stderr bytes.Buffer
			cmd := &cobra.Command{}
			cmd.SetOut(&out)
			cmd.SetErr(&stderr)
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			cmd.SetContext(ctx)
			err := updateCmd.RunE(cmd, nil)
			if err == nil || !strings.Contains(err.Error(), "no asset matching") {
				t.Fatalf("should reach existing asset check, not replace binary: %v", err)
			}
			got := stderr.String()
			for _, want := range []string{tc.want, "kiln", "0.0.22", "responding edges only"} {
				if !strings.Contains(got, want) {
					t.Errorf("missing %q: %s", want, got)
				}
			}
			if !tc.missing && tc.name == "target-differs-from-bundled" && !strings.Contains(got, "0.0.99") {
				t.Fatal(got)
			}
			if strings.Contains(out.String(), "Python SDK") {
				t.Fatal("stdout changed")
			}
		})
	}
}

func TestUpdateCompatibilityUsesTargetPolicyAndGuidance(t *testing.T) {
	p, err := compatibility.Parse([]byte(`{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.99","max":"0.0.99"}}]}`))
	if err != nil {
		t.Fatal(err)
	}
	results := []pudanats.PingResult{
		{MachineID: "newly-affected", Status: "pong", SDKVersion: "0.0.21"},
		{MachineID: "already-unlisted", Status: "pong", SDKVersion: "0.0.98"},
		{MachineID: "target-supported", Status: "pong", SDKVersion: "0.0.99"},
		{MachineID: "missing-version", Status: "pong"},
		{MachineID: "development", Status: "pong", SDKVersion: "dev"},
		{MachineID: "offline", Status: "timeout"},
		{MachineID: "newly-affected", Status: "pong", SDKVersion: "0.0.21"},
	}
	var out bytes.Buffer
	writeCompatibilityWarnings(&out, results, "v0.1.6", p, "0.1.5")
	got := out.String()
	for _, want := range []string{"newly-affected", "0.0.21", "0.0.99", "upgrade/change", "newly unsupported by target", "already outside the supported range of current CLI", "missing-version", "development", "compatibility unknown"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing %q: %s", want, got)
		}
	}
	if strings.Contains(got, "target-supported") || strings.Contains(got, "offline") || strings.Count(got, `machine "newly-affected"`) != 1 {
		t.Fatal(got)
	}
}

func TestUpdateFleetUsesOnlyFreshResponders(t *testing.T) {
	url, nc, _ := healthcheckTestBroker(t, true)
	healthcheckTestConfig(t, url, "")
	_, err := nc.Subscribe("puda.cmd.ping", func(m *natsio.Msg) {
		_ = m.Respond([]byte(`{"machine_id":"oven","status":"pong","sdk_version":"0.0.21"}`))
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := nc.Flush(); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	// Use an independent target fixture: bundled policies evolve after qualification.
	target, err := compatibility.Parse([]byte(`{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.99","max":"0.0.99"}}]}`))
	if err != nil {
		t.Fatal(err)
	}
	writeFleetCompatibility(&out, url, 50*time.Millisecond, "0.1.6", target, "0.1.5")
	if !strings.Contains(out.String(), "newly unsupported by target") || !strings.Contains(out.String(), "oven") || !strings.Contains(out.String(), "0.0.99") {
		t.Fatal(out.String())
	}
}
