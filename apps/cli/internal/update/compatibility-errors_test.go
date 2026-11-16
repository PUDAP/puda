package update

import (
	"context"
	"encoding/base64"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	compatibility "github.com/PUDAP/puda"
)

func TestTargetCompatibilityRedirectAndTagCycleAreBounded(t *testing.T) {
	for _, redirect := range []bool{true, false} {
		t.Run(fmt.Sprint(redirect), func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if redirect {
					http.Redirect(w, r, "https://untrusted.invalid/policy", http.StatusFound)
					return
				}
				fmt.Fprintf(w, `{"object":{"type":"tag","sha":%q}}`, strings.Repeat("a", 40))
			}))
			defer server.Close()
			base, err := url.Parse(server.URL)
			if err != nil {
				t.Fatal(err)
			}
			old := http.DefaultTransport
			http.DefaultTransport = localUpdateTransport{base, old}
			defer func() { http.DefaultTransport = old }()
			p, err := FetchCompatibility(context.Background(), "v0.1.6")
			if err == nil || p.Evaluate("0.1.6", "0.0.22").Status != compatibility.Unknown {
				t.Fatalf("policy=%+v err=%v", p, err)
			}
			want := 6
			if redirect {
				want = 1
			}
			if calls != want {
				t.Fatalf("requests=%d want=%d", calls, want)
			}
		})
	}
}

func TestTargetCompatibilityMetadataErrors(t *testing.T) {
	for _, tc := range []struct {
		name    string
		status  int
		content string
	}{
		{"missing-file", 404, ""}, {"rate-limited", 403, ""}, {"unavailable", 503, ""},
		{"malformed-json", 200, "{"}, {"missing-encoding", 200, `{"content":"e30="}`},
		{"invalid-base64", 200, `{"encoding":"base64","content":"!"}`},
		{"invalid-policy", 200, `{"encoding":"base64","content":"ew=="}`},
		{"too-large", 200, strings.Repeat(" ", compatibilityMaxBytes+1)},
	} {
		t.Run(tc.name, func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.URL.Path == "/git/ref/tags/v0.1.6" {
					fmt.Fprintf(w, `{"object":{"type":"commit","sha":%q}}`, strings.Repeat("a", 40))
					return
				}
				if r.URL.Path != "/contents/compatibility.json" {
					t.Errorf("unexpected fallback: %s", r.URL)
				}
				w.WriteHeader(tc.status)
				fmt.Fprint(w, tc.content)
			}))
			defer server.Close()
			p, err := fetchCompatibility(context.Background(), server.Client(), server.URL, "v0.1.6")
			if err == nil || p.Evaluate("0.1.6", "0.0.22").Status != compatibility.Unknown {
				t.Fatalf("policy=%+v err=%v", p, err)
			}
			if calls != 2 {
				t.Fatalf("unexpected fallback requests: %d", calls)
			}
		})
	}
}

func TestTargetCompatibilityMissingEntryNeverUsesBundled(t *testing.T) {
	for _, policy := range []string{`{}`, `{"compatibility":[{"cli":{"min":"0.1.5","max":"0.1.5"},"python_sdk":{"min":"0.0.22","max":"0.0.22"}}]}`, `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"bad-version","max":"0.0.22"}}]}`} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if strings.HasPrefix(r.URL.Path, "/git/ref/") {
				fmt.Fprintf(w, `{"object":{"type":"commit","sha":%q}}`, strings.Repeat("a", 40))
				return
			}
			fmt.Fprintf(w, `{"encoding":"base64","content":%q}`, base64.StdEncoding.EncodeToString([]byte(policy)))
		}))
		p, err := fetchCompatibility(context.Background(), server.Client(), server.URL, "v0.1.6")
		server.Close()
		if err != nil {
			t.Fatal(err)
		}
		if p.Evaluate("0.1.6", "0.0.22").Status != compatibility.Unknown {
			t.Fatalf("fallback approval: %+v", p)
		}
	}
}

func TestReleaseNotificationCheckDoesNotPreflight(t *testing.T) {
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
