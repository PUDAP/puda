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

func TestReleaseNotificationCheckFetchesOnlyLatest(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if !strings.HasSuffix(r.URL.Path, "/releases/latest") {
			t.Errorf("check-only fetched %s", r.URL)
		}
		fmt.Fprint(w, `{"tag_name":"v0.1.6"}`)
	}))
	defer server.Close()
	base, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	old := http.DefaultTransport
	http.DefaultTransport = localUpdateTransport{base, old}
	defer func() { http.DefaultTransport = old }()
	rel, err := fetchLatestRelease()
	if err != nil || rel.TagName != "v0.1.6" || calls != 1 {
		t.Fatalf("release=%+v err=%v calls=%d", rel, err, calls)
	}
}

func TestUpdateConfirmationAndAlreadyLatest(t *testing.T) {
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
		want          string
	}{
		{"already-latest", "0.1.6", true, "Nothing to do"},
		{"noninteractive-continues", "0.1.5", true, ""},
		{"decline-keeps-confirmation", "0.1.5", false, "Aborted"},
		{"downgrade-keeps-confirmation", "0.1.7", false, "Aborted"},
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
			var out bytes.Buffer
			cmd := &cobra.Command{}
			cmd.SetOut(&out)
			cmd.SetErr(&out)
			err = Run(cmd, "", tc.yes, tc.current)
			if tc.want != "" {
				if err != nil || !strings.Contains(out.String(), tc.want) {
					t.Fatalf("err=%v out=%s", err, out.String())
				}
			} else if err == nil || !strings.Contains(err.Error(), "no asset matching") {
				t.Fatalf("confirmed update did not reach download: %v", err)
			}
		})
	}
}
