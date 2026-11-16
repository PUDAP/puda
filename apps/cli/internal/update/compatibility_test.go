package update

import (
	"context"
	"encoding/base64"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	compatibility "github.com/PUDAP/puda"
)

func TestTargetCompatibilityRejectsMalformedTagBeforeLookup(t *testing.T) {
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { requests++; http.NotFound(w, r) }))
	defer server.Close()
	for _, tag := range []string{" v0.1.6", "v0.1.6 ", "v0.1.6-../../main", "main", "v01.1.6", "v1", "v0.1.6?ref=main"} {
		if _, err := fetchCompatibility(context.Background(), server.Client(), server.URL, tag); err == nil {
			t.Errorf("accepted %q", tag)
		}
	}
	if requests != 0 {
		t.Fatalf("malformed tags triggered %d lookups", requests)
	}
}

func TestTargetCompatibilityPinnedSource(t *testing.T) {
	sha := strings.Repeat("a", 40)
	var paths []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.RequestURI())
		switch r.URL.Path {
		case "/git/ref/tags/v0.1.6":
			fmt.Fprintf(w, `{"object":{"type":"tag","sha":%q}}`, strings.Repeat("b", 40))
		case "/git/tags/" + strings.Repeat("b", 40):
			fmt.Fprintf(w, `{"object":{"type":"commit","sha":%q}}`, sha)
		case "/contents/compatibility.json":
			if r.URL.Query().Get("ref") != sha {
				t.Errorf("not pinned: %s", r.URL)
			}
			data := `{"compatibility":[{"cli":{"min":"0.1.6","max":"0.1.6"},"python_sdk":{"min":"0.0.99","max":"0.0.99"}}]}`
			fmt.Fprintf(w, `{"encoding":"base64","content":%q}`, base64.StdEncoding.EncodeToString([]byte(data)))
		default:
			t.Errorf("unexpected URL: %s", r.URL)
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	p, err := fetchCompatibility(context.Background(), server.Client(), server.URL, "v0.1.6")
	if err != nil {
		t.Fatal(err)
	}
	if p.Evaluate("0.1.6", "0.0.99").Status != compatibility.Supported || p.Evaluate("0.1.6", "0.0.22").Status != compatibility.Unsupported {
		t.Fatalf("used installed policy: %+v", p)
	}
	if len(paths) != 3 {
		t.Fatalf("requests: %v", paths)
	}
}

func TestTargetCompatibilityFailuresRemainUnknown(t *testing.T) {
	for _, body := range []string{`{`, `{}`, `{"object":{"type":"commit","sha":"main"}}`} {
		t.Run(body, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, body) }))
			defer server.Close()
			p, err := fetchCompatibility(context.Background(), server.Client(), server.URL, "v0.1.6")
			if err == nil || p.Evaluate("0.1.6", "0.0.22").Status != compatibility.Unknown {
				t.Fatalf("policy=%+v err=%v", p, err)
			}
		})
	}
	t.Run("deadline", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() }))
		defer server.Close()
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
		defer cancel()
		if _, err := fetchCompatibility(ctx, server.Client(), server.URL, "v0.1.6"); err == nil {
			t.Fatal("missing timeout")
		}
	})
}
