package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

func TestConfigSetAllowsUserID(t *testing.T) {
	cfg := setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})

	cmd := newConfigSetCommand()
	if err := runConfigSet(cmd, []string{configKeyUserID, "custom-user-id"}); err != nil {
		t.Fatalf("runConfigSet: %v", err)
	}

	got, err := puda.LoadGlobalConfig()
	if err != nil {
		t.Fatalf("LoadGlobalConfig: %v", err)
	}
	if got.User.UserID != "custom-user-id" {
		t.Fatalf("user_id=%q, want custom-user-id", got.User.UserID)
	}
	if got.User.Username != cfg.User.Username {
		t.Fatalf("username changed to %q", got.User.Username)
	}
	if out := cmd.OutOrStdout().(*bytes.Buffer).String(); out != "user.user_id=custom-user-id\n" {
		t.Fatalf("output=%q", out)
	}
}

func TestConfigSetSyncsProjectUserID(t *testing.T) {
	setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})

	projectDir := t.TempDir()
	t.Chdir(projectDir)
	projectCfg := puda.ProjectConfig{
		User:        puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
		Database:    puda.ConfigDatabase{Path: "puda.db"},
		ProjectRoot: projectDir,
	}
	data, err := json.MarshalIndent(projectCfg, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(puda.ProjectConfigPathForDir(projectDir), data, 0o644); err != nil {
		t.Fatal(err)
	}

	cmd := newConfigSetCommand()
	if err := runConfigSet(cmd, []string{configKeyUserID, "project-user-id"}); err != nil {
		t.Fatalf("runConfigSet: %v", err)
	}

	got, err := puda.LoadProjectConfig()
	if err != nil {
		t.Fatalf("LoadProjectConfig: %v", err)
	}
	if got.User.UserID != "project-user-id" {
		t.Fatalf("project user_id=%q, want project-user-id", got.User.UserID)
	}
}

func TestConfigSetRejectsEmptyUserID(t *testing.T) {
	setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})

	err := runConfigSet(newConfigSetCommand(), []string{configKeyUserID, "   "})
	if err == nil || !strings.Contains(err.Error(), "cannot be empty") {
		t.Fatalf("error=%v, want empty user_id error", err)
	}
}

func TestConfigSetAllowsUsername(t *testing.T) {
	setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})

	cmd := newConfigSetCommand()
	if err := runConfigSet(cmd, []string{configKeyUsername, "bearspuda"}); err != nil {
		t.Fatalf("runConfigSet: %v", err)
	}

	got, err := puda.LoadGlobalConfig()
	if err != nil {
		t.Fatalf("LoadGlobalConfig: %v", err)
	}
	if got.User.Username != "bearspuda" {
		t.Fatalf("username=%q, want bearspuda", got.User.Username)
	}
	if got.User.UserID != "generated-id" {
		t.Fatalf("user_id changed to %q", got.User.UserID)
	}
	if out := cmd.OutOrStdout().(*bytes.Buffer).String(); out != "user.username=bearspuda\n" {
		t.Fatalf("output=%q", out)
	}
}

func TestConfigSetSyncsProjectUsername(t *testing.T) {
	setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})

	projectDir := t.TempDir()
	t.Chdir(projectDir)
	projectCfg := puda.ProjectConfig{
		User:        puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
		Database:    puda.ConfigDatabase{Path: "puda.db"},
		ProjectRoot: projectDir,
	}
	data, err := json.MarshalIndent(projectCfg, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(puda.ProjectConfigPathForDir(projectDir), data, 0o644); err != nil {
		t.Fatal(err)
	}

	cmd := newConfigSetCommand()
	if err := runConfigSet(cmd, []string{configKeyUsername, "bearspuda"}); err != nil {
		t.Fatalf("runConfigSet: %v", err)
	}

	got, err := puda.LoadProjectConfig()
	if err != nil {
		t.Fatalf("LoadProjectConfig: %v", err)
	}
	if got.User.Username != "bearspuda" {
		t.Fatalf("project username=%q, want bearspuda", got.User.Username)
	}
	if got.User.UserID != "generated-id" {
		t.Fatalf("project user_id changed to %q", got.User.UserID)
	}
}

func TestConfigSetRejectsEmptyUsername(t *testing.T) {
	setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})

	err := runConfigSet(newConfigSetCommand(), []string{configKeyUsername, "   "})
	if err == nil || !strings.Contains(err.Error(), "cannot be empty") {
		t.Fatalf("error=%v, want empty username error", err)
	}
}

func TestConfigGetUserID(t *testing.T) {
	setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})

	cmd := newConfigSetCommand()
	if err := runConfigGet(cmd, []string{configKeyUserID}); err != nil {
		t.Fatalf("runConfigGet: %v", err)
	}
	if out := cmd.OutOrStdout().(*bytes.Buffer).String(); out != "generated-id\n" {
		t.Fatalf("output=%q", out)
	}
}

func newConfigSetCommand() *cobra.Command {
	cmd := &cobra.Command{Use: "set"}
	cmd.SetOut(&bytes.Buffer{})
	return cmd
}

func setupGlobalConfig(t *testing.T, cfg puda.GlobalConfig) puda.GlobalConfig {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
	t.Setenv("AppData", home)

	if err := puda.SaveGlobalConfig(&cfg); err != nil {
		t.Fatalf("SaveGlobalConfig: %v", err)
	}
	return cfg
}
