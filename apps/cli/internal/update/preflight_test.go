package update

import (
	"bytes"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

type localUpdateTransport struct {
	base      *url.URL
	transport http.RoundTripper
}

func (r localUpdateTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	clone := req.Clone(req.Context())
	u := *req.URL
	clone.URL = &u
	clone.URL.Scheme = r.base.Scheme
	clone.URL.Host = r.base.Host
	return r.transport.RoundTrip(clone)
}

func TestUpdatePreflightOrderingAndAlreadyLatest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/releases/latest") {
			fmt.Fprint(w, `{"tag_name":"v0.1.6","assets":[]}`)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/releases") {
			fmt.Fprint(w, `[]`)
			return
		}
		t.Errorf("unexpected network request %s", r.URL)
		http.NotFound(w, r)
	}))
	defer server.Close()
	base, _ := url.Parse(server.URL)
	oldTransport := http.DefaultTransport
	http.DefaultTransport = localUpdateTransport{base, oldTransport}
	t.Cleanup(func() { http.DefaultTransport = oldTransport })
	for _, tc := range []struct {
		name, current string
		yes           bool
		calls         int
		want          string
	}{
		{"already-latest", "0.1.6", true, 0, "Nothing to do"},
		{"noninteractive-advisory-continues", "0.1.5", true, 1, ""},
		{"decline-keeps-confirmation", "0.1.5", false, 1, "Aborted"},
		{"downgrade-keeps-confirmation", "0.1.7", false, 1, "Aborted"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			input, err := os.CreateTemp(t.TempDir(), "stdin")
			if err != nil {
				t.Fatal(err)
			}
			defer input.Close()
			if _, err = input.WriteString("n\n"); err != nil {
				t.Fatal(err)
			}
			if _, err = input.Seek(0, 0); err != nil {
				t.Fatal(err)
			}
			oldIn := os.Stdin
			os.Stdin = input
			defer func() { os.Stdin = oldIn }()
			var out, stderr bytes.Buffer
			cmd := &cobra.Command{}
			cmd.SetOut(&out)
			cmd.SetErr(&stderr)
			calls := 0
			err = Run(cmd, "", tc.yes, tc.current, func(tag string) {
				calls++
				if tag != "v0.1.6" {
					t.Errorf("tag=%s", tag)
				}
				if strings.Contains(out.String(), "Would you like") || strings.Contains(out.String(), "Are you sure") || strings.Contains(out.String(), "Downloading") {
					t.Errorf("preflight too late: %s", out.String())
				}
				fmt.Fprintln(cmd.ErrOrStderr(), "compatibility unknown (advisory only)")
			})
			if calls != tc.calls {
				t.Fatalf("calls=%d", calls)
			}
			if tc.want != "" {
				if err != nil || !strings.Contains(out.String(), tc.want) {
					t.Fatalf("err=%v out=%s", err, out.String())
				}
			} else if err == nil || !strings.Contains(err.Error(), "no asset matching") {
				t.Fatalf("advisory blocked existing path: %v", err)
			}
			if strings.Contains(out.String(), "compatibility") {
				t.Fatal("advisory polluted stdout")
			}
		})
	}
}
