package update

import (
	"strings"
	"testing"
)

func TestBuildNotice(t *testing.T) {
	tests := []struct {
		name     string
		current  string
		latest   string
		wantSoft bool // patch-only: "A new version … is available"
		wantHard bool // minor/major: "You are running an outdated version"
	}{
		{"up to date", "v0.1.3", "v0.1.3", false, false},
		{"current is newer", "v0.1.3", "v0.1.2", false, false},
		{"patch bump", "v0.1.0", "v0.1.3", true, false},
		{"minor bump", "v0.1.0", "v0.2.0", false, true},
		{"major bump", "v0.1.0", "v1.0.0", false, true},
		{"dev build: silent", "dev", "v0.2.0", false, false},
		{"unparseable latest: silent", "v0.1.0", "nightly", false, false},
		{"no v prefix current", "0.1.0", "v0.2.0", false, true},
		{"no v prefix both", "0.1.0", "0.2.0", false, true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			msg := buildNotice(tc.current, tc.latest)
			hasSoft := msg != "" && strings.Contains(msg, "A new version")
			hasHard := strings.Contains(msg, "outdated")

			if hasSoft != tc.wantSoft {
				t.Errorf("soft notice: got %v, want %v (msg=%q)", hasSoft, tc.wantSoft, msg)
			}
			if hasHard != tc.wantHard {
				t.Errorf("hard notice: got %v, want %v (msg=%q)", hasHard, tc.wantHard, msg)
			}
		})
	}
}

func TestBuildNoticePatchContainsLatestVersion(t *testing.T) {
	msg := buildNotice("v0.1.0", "v0.1.5")
	if !strings.Contains(msg, "v0.1.5") {
		t.Errorf("expected latest version in soft notice, got: %q", msg)
	}
}

func TestBuildNoticeHardContainsBothVersions(t *testing.T) {
	msg := buildNotice("v0.1.0", "v0.3.0")
	if !strings.Contains(msg, "v0.1.0") {
		t.Errorf("expected current version in hard notice, got: %q", msg)
	}
	if !strings.Contains(msg, "v0.3.0") {
		t.Errorf("expected latest version in hard notice, got: %q", msg)
	}
}

func TestBuildNoticeWritesToStderr(t *testing.T) {
	// Ensure the message ends with a newline so it renders cleanly on stderr.
	for _, tc := range []struct{ cur, lat string }{
		{"v0.1.0", "v0.1.9"},
		{"v0.1.0", "v0.9.0"},
	} {
		msg := buildNotice(tc.cur, tc.lat)
		if msg == "" {
			t.Errorf("buildNotice(%q, %q) returned empty", tc.cur, tc.lat)
			continue
		}
		if !strings.HasSuffix(msg, "\n") {
			t.Errorf("notice does not end with newline: %q", msg)
		}
	}
}
