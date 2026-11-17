package cli

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// isolatedConfigPath points every OS config-directory variable at a temp dir
// and returns the global config path there. No file is created.
func isolatedConfigPath(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
	t.Setenv("AppData", home)
	path, err := puda.GlobalConfigPath()
	if err != nil {
		t.Fatal(err)
	}
	return path
}

func writeRawConfig(t *testing.T, path, raw string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(raw), 0o600); err != nil {
		t.Fatal(err)
	}
}

func readConfigFile(t *testing.T, path string) puda.GlobalConfig {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cfg puda.GlobalConfig
	if err := json.Unmarshal(data, &cfg); err != nil {
		t.Fatalf("parse %s: %v", data, err)
	}
	return cfg
}

func runWithOutput(t *testing.T, run func(*cobra.Command, []string) error) (string, error) {
	t.Helper()
	cmd := &cobra.Command{Use: "test"}
	var out bytes.Buffer
	cmd.SetOut(&out)
	err := run(cmd, nil)
	return out.String(), err
}

func runLoginAs(t *testing.T, username string) (string, error) {
	t.Helper()
	previous := loginUsername
	loginUsername = username
	t.Cleanup(func() { loginUsername = previous })
	return runWithOutput(t, runLogin)
}

const profileConfig = `"active_profile":"lab","profiles":{"lab":{"nats_servers":"tls://lab:4222","e2e":true,"ca":"/k/ca.pem","key_file":"/k/e2e.key"}}`

func assertLabProfile(t *testing.T, cfg puda.GlobalConfig) {
	t.Helper()
	lab, ok := cfg.Profiles["lab"]
	if cfg.ActiveProfile != "lab" || !ok || lab.NATSServers != "tls://lab:4222" || !lab.E2E || lab.CA != "/k/ca.pem" || lab.KeyFile != "/k/e2e.key" {
		t.Fatalf("profile settings lost: %+v", cfg)
	}
}

func TestLoginOverDefaultIdentityKeepsUserID(t *testing.T) {
	path := isolatedConfigPath(t)
	writeRawConfig(t, path, `{"user":{"username":"osuser","user_id":"default-id","default":true},`+profileConfig+`}`)

	out, err := runLoginAs(t, " zhao ")
	if err != nil {
		t.Fatalf("login: %v", err)
	}
	if strings.Contains(out, "Contacting") || strings.Contains(out, "Authenticating") || strings.Contains(out, "Fetching") {
		t.Fatalf("login printed simulated auth messages: %q", out)
	}
	if !strings.Contains(out, "zhao") {
		t.Fatalf("output=%q", out)
	}
	cfg := readConfigFile(t, path)
	if cfg.User != (puda.ConfigUser{Username: "zhao", UserID: "default-id"}) {
		t.Fatalf("user=%+v", cfg.User)
	}
	assertLabProfile(t, cfg)
}

func TestLoginWithoutConfigCreatesExplicitIdentity(t *testing.T) {
	path := isolatedConfigPath(t)
	if _, err := runLoginAs(t, "zhao"); err != nil {
		t.Fatalf("login: %v", err)
	}
	cfg := readConfigFile(t, path)
	if cfg.User.Username != "zhao" || cfg.User.UserID == "" || cfg.User.Default {
		t.Fatalf("user=%+v", cfg.User)
	}
}

func TestLoginWhenExplicitlyLoggedInIsUnchanged(t *testing.T) {
	path := isolatedConfigPath(t)
	raw := `{"user":{"username":"zhao","user_id":"id-1"},` + profileConfig + `}`
	writeRawConfig(t, path, raw)

	out, err := runLoginAs(t, "other")
	if err != nil {
		t.Fatalf("login: %v", err)
	}
	if out != "You are already logged in as zhao.\n" {
		t.Fatalf("output=%q", out)
	}
	if data, _ := os.ReadFile(path); string(data) != raw {
		t.Fatalf("config changed: %s", data)
	}
}

func TestLoginParseErrorLeavesConfigIntact(t *testing.T) {
	path := isolatedConfigPath(t)
	writeRawConfig(t, path, "{bad json")

	if _, err := runLoginAs(t, "zhao"); err == nil {
		t.Fatal("expected parse error")
	}
	if data, err := os.ReadFile(path); err != nil || string(data) != "{bad json" {
		t.Fatalf("config deleted or modified: %q err=%v", data, err)
	}
}

func TestLogoutClearsOnlyIdentity(t *testing.T) {
	path := isolatedConfigPath(t)
	writeRawConfig(t, path, `{"user":{"username":"zhao","user_id":"id-1"},`+profileConfig+`}`)

	out, err := runWithOutput(t, runLogout)
	if err != nil {
		t.Fatalf("logout: %v", err)
	}
	if !strings.Contains(out, "zhao") {
		t.Fatalf("output=%q", out)
	}
	cfg := readConfigFile(t, path)
	if cfg.User != (puda.ConfigUser{}) {
		t.Fatalf("identity not cleared: %+v", cfg.User)
	}
	assertLabProfile(t, cfg)

	next, err := puda.LoadGlobalConfig()
	if err != nil {
		t.Fatal(err)
	}
	if !next.User.Default || next.User.UserID == "" || next.User.UserID == "id-1" {
		t.Fatalf("expected a fresh default identity after logout: %+v", next.User)
	}
}

func TestLogoutWithoutExplicitLoginIsNoop(t *testing.T) {
	path := isolatedConfigPath(t)
	out, err := runWithOutput(t, runLogout)
	if err != nil || out != "You are not logged in.\n" {
		t.Fatalf("out=%q err=%v", out, err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("logout created a config file: %v", err)
	}

	raw := `{"user":{"username":"osuser","user_id":"default-id","default":true},` + profileConfig + `}`
	writeRawConfig(t, path, raw)
	out, err = runWithOutput(t, runLogout)
	if err != nil || !strings.HasPrefix(out, "You are not logged in.") {
		t.Fatalf("out=%q err=%v", out, err)
	}
	if data, _ := os.ReadFile(path); string(data) != raw {
		t.Fatalf("config changed: %s", data)
	}
}

func TestLogoutParseErrorLeavesConfigIntact(t *testing.T) {
	path := isolatedConfigPath(t)
	writeRawConfig(t, path, "{bad json")
	if _, err := runWithOutput(t, runLogout); err == nil {
		t.Fatal("expected parse error")
	}
	if data, err := os.ReadFile(path); err != nil || string(data) != "{bad json" {
		t.Fatalf("config deleted or modified: %q err=%v", data, err)
	}
}

func TestConfigListShowsDefaultIdentity(t *testing.T) {
	path := isolatedConfigPath(t)
	out, err := runWithOutput(t, runConfigList)
	if err != nil {
		t.Fatalf("config list: %v", err)
	}
	cfg := readConfigFile(t, path)
	want := "user.user_id=" + cfg.User.UserID + "\nuser.username=" + cfg.User.Username + "\nuser.default=true\n"
	if out != want {
		t.Fatalf("output=%q want %q", out, want)
	}
}

func TestConfigGetDefault(t *testing.T) {
	path := isolatedConfigPath(t)
	writeRawConfig(t, path, `{"user":{"username":"zhao","user_id":"id-1"}}`)
	cmd := newConfigSetCommand()
	if err := runConfigGet(cmd, []string{"user.default"}); err != nil {
		t.Fatal(err)
	}
	if out := cmd.OutOrStdout().(*bytes.Buffer).String(); out != "false\n" {
		t.Fatalf("output=%q", out)
	}
}

func TestConfigSetUsernameClearsDefaultMarker(t *testing.T) {
	path := isolatedConfigPath(t)
	writeRawConfig(t, path, `{"user":{"username":"osuser","user_id":"default-id","default":true}}`)
	if err := runConfigSet(newConfigSetCommand(), []string{configKeyUsername, "zhao"}); err != nil {
		t.Fatal(err)
	}
	if cfg := readConfigFile(t, path); cfg.User != (puda.ConfigUser{Username: "zhao", UserID: "default-id"}) {
		t.Fatalf("user=%+v", cfg.User)
	}
}

func TestInitUsesDefaultIdentityWithoutLogin(t *testing.T) {
	path := isolatedConfigPath(t)
	target := t.TempDir()
	cfg, err := loadOrCreateProjectConfig(puda.ProjectConfigPathForDir(target), target)
	if err != nil {
		t.Fatalf("init without login: %v", err)
	}
	global := readConfigFile(t, path)
	if !global.User.Default || cfg.User.Username != global.User.Username || cfg.User.UserID != global.User.UserID {
		t.Fatalf("project user=%+v global user=%+v", cfg.User, global.User)
	}
}

func TestMachineCommandsDoNotRequireLogin(t *testing.T) {
	cases := map[string]func() error{
		"run": func() error {
			cmd := &cobra.Command{Use: "run"}
			cmd.SetOut(io.Discard)
			return runSingleMachineCommand(cmd, "m1", "noop", nil, nil, "")
		},
		"immediate": func() error {
			_, err := sendImmediateCommandToMachines([]string{"m1"}, "Start", "", nil)
			return err
		},
		"update": func() error { return runMachineUpdate(io.Discard, "m1") },
		"home":   func() error { return homeMachines(io.Discard, []string{"m1"}) },
	}
	for name, run := range cases {
		t.Run(name, func(t *testing.T) {
			path := isolatedConfigPath(t)
			err := run()
			// No profile is configured, so the command stops at the connection.
			if err == nil {
				t.Fatal("expected missing-profile error")
			}
			if strings.Contains(err.Error(), "login") {
				t.Fatalf("command still requires login: %v", err)
			}
			if cfg := readConfigFile(t, path); !cfg.User.Default || cfg.User.UserID == "" {
				t.Fatalf("default identity not persisted: %+v", cfg.User)
			}
		})
	}
}

func TestConfigEditCreatesDefaultIdentity(t *testing.T) {
	path := isolatedConfigPath(t)
	t.Setenv("EDITOR", "true")
	if _, err := runWithOutput(t, runConfigEdit); err != nil {
		t.Fatalf("config edit: %v", err)
	}
	if cfg := readConfigFile(t, path); !cfg.User.Default {
		t.Fatalf("user=%+v", cfg.User)
	}
}
