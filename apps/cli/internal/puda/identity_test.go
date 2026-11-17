package puda

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func isolateConfigHome(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
	t.Setenv("AppData", home)
	path, err := GlobalConfigPath()
	if err != nil {
		t.Fatal(err)
	}
	return path
}

func stubOSUsername(t *testing.T, name string) {
	t.Helper()
	previous := osUsername
	osUsername = func() string { return name }
	t.Cleanup(func() { osUsername = previous })
}

func TestLoadGlobalConfigCreatesAndReusesDefaultIdentity(t *testing.T) {
	path := isolateConfigHome(t)
	stubOSUsername(t, "alice")

	first, err := LoadGlobalConfig()
	if err != nil {
		t.Fatalf("LoadGlobalConfig: %v", err)
	}
	if first.User.Username != "alice" || !first.User.Default || first.User.UserID == "" {
		t.Fatalf("user=%+v", first.User)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("default identity was not persisted: %v", err)
	}
	if runtime.GOOS != "windows" {
		if info.Mode().Perm() != 0o600 {
			t.Fatalf("config mode=%v", info.Mode().Perm())
		}
		dirInfo, err := os.Stat(filepath.Dir(path))
		if err != nil || dirInfo.Mode().Perm() != 0o700 {
			t.Fatalf("config dir mode=%v err=%v", dirInfo.Mode().Perm(), err)
		}
	}

	second, err := LoadGlobalConfig()
	if err != nil {
		t.Fatalf("second LoadGlobalConfig: %v", err)
	}
	if second.User != first.User {
		t.Fatalf("identity changed between runs: %+v vs %+v", first.User, second.User)
	}
}

func TestLoadGlobalConfigAddsDefaultIdentityPreservingProfiles(t *testing.T) {
	path := isolateConfigHome(t)
	stubOSUsername(t, "bob")
	original := `{"user":{"username":"","user_id":""},"active_profile":"lab","profiles":{"lab":{"nats_servers":"tls://lab:4222","e2e":true,"ca":"/k/ca.pem","key_file":"/k/e2e.key"}}}`
	if err := os.WriteFile(path, []byte(original), 0o600); err != nil {
		t.Fatal(err)
	}

	cfg, err := LoadGlobalConfig()
	if err != nil {
		t.Fatalf("LoadGlobalConfig: %v", err)
	}
	if cfg.User.Username != "bob" || !cfg.User.Default || cfg.User.UserID == "" {
		t.Fatalf("user=%+v", cfg.User)
	}

	var onDisk GlobalConfig
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, &onDisk); err != nil {
		t.Fatal(err)
	}
	if onDisk.User != cfg.User {
		t.Fatalf("persisted user=%+v want %+v", onDisk.User, cfg.User)
	}
	lab := onDisk.Profiles["lab"]
	if onDisk.ActiveProfile != "lab" || lab.NATSServers != "tls://lab:4222" || !lab.E2E || lab.CA != "/k/ca.pem" || lab.KeyFile != "/k/e2e.key" {
		t.Fatalf("profiles not preserved: %s", data)
	}
}

func TestLoadGlobalConfigKeepsExplicitIdentity(t *testing.T) {
	path := isolateConfigHome(t)
	stubOSUsername(t, "ignored")
	if err := os.WriteFile(path, []byte(`{"user":{"username":"zhao","user_id":"id-1"}}`), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err := LoadGlobalConfig()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.User != (ConfigUser{Username: "zhao", UserID: "id-1"}) {
		t.Fatalf("user=%+v", cfg.User)
	}
}

func TestLoadGlobalConfigParseErrorLeavesFileIntact(t *testing.T) {
	path := isolateConfigHome(t)
	if err := os.WriteFile(path, []byte("{bad json"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadGlobalConfig(); err == nil {
		t.Fatal("expected parse error")
	}
	data, err := os.ReadFile(path)
	if err != nil || string(data) != "{bad json" {
		t.Fatalf("config modified: %q err=%v", data, err)
	}
}

func TestSanitizeOSUsername(t *testing.T) {
	cases := map[string]string{
		"alice":             "alice",
		"  bob  ":           "bob",
		`CORP\Carol`:        "Carol",
		`CORP\Dan Smith`:    "Dan-Smith",
		"eve@example.com":   "eve-example.com",
		"":                  "puda-user",
		"   ":               "puda-user",
		`CORP\`:             "puda-user",
		"\x00\x01":          "puda-user",
		"frank_o.neil-test": "frank_o.neil-test",
	}
	for raw, want := range cases {
		if got := sanitizeUsername(raw); got != want {
			t.Errorf("sanitizeUsername(%q)=%q want %q", raw, got, want)
		}
	}
}
