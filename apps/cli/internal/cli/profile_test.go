package cli

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

func TestProfilesPlainAndEncrypted(t *testing.T) {
	t.Cleanup(pudanats.ResetSession)
	t.Chdir(t.TempDir())
	setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})
	ca, key := writeProfileMaterial(t)

	activated, err := addProfile("bears", "nats://bears:4222", "", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if !activated {
		t.Fatal("first profile should become active")
	}
	if _, err := addProfile("imre", "tls://imre:4222", "tls://other:4222", ca, key); err != nil {
		t.Fatal(err)
	}
	if _, err := addProfile("bad", "nats://x:4222", "", ca, ""); err == nil {
		t.Fatal("expected --ca without --key to fail")
	}
	if _, err := addProfile("mixed", "nats://a:4222, tls://b:4222", "", "", ""); err == nil {
		t.Fatal("expected mixed schemes to fail")
	}
	if _, err := addProfile("imre", "tls://imre:4222", "", ca, key); err == nil {
		t.Fatal("expected duplicate profile to fail")
	}

	var list bytes.Buffer
	if err := listProfiles(&list, true); err != nil {
		t.Fatal(err)
	}
	if list.String() != "* bears nats://bears:4222 plain\n  imre tls://imre:4222 e2e\n" {
		t.Fatalf("list=%q", list.String())
	}
	var listed profileList
	var jsonList bytes.Buffer
	if err := listProfiles(&jsonList, false); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(jsonList.Bytes(), &listed); err != nil {
		t.Fatal(err)
	}
	if listed.Active != "bears" || len(listed.Profiles) != 2 || !listed.Profiles[0].Active || !listed.Profiles[1].E2E {
		t.Fatalf("json list=%s", jsonList.String())
	}
	if strings.Contains(jsonList.String(), `"ca": ""`) || strings.Contains(jsonList.String(), `"key_file": ""`) {
		t.Fatalf("plaintext profile included empty encryption fields: %s", jsonList.String())
	}
	if !strings.Contains(jsonList.String(), `"ca": "`+ca+`"`) || !strings.Contains(jsonList.String(), `"key_file": "`+key+`"`) {
		t.Fatalf("encrypted profile omitted ca or key_file: %s", jsonList.String())
	}

	if err := switchProfile("imre"); err != nil {
		t.Fatal(err)
	}
	var current bytes.Buffer
	if err := printCurrentProfile(&current, true); err != nil {
		t.Fatal(err)
	}
	got := current.String()
	for _, line := range []string{
		"name=imre\n",
		"nats_servers=tls://imre:4222\n",
		"gateway_servers=tls://other:4222\n",
		"e2e=true\n",
		"ca=" + ca + "\n",
		"key_file=" + key + "\n",
	} {
		if !strings.Contains(got, line) {
			t.Fatalf("current missing %q in %q", line, got)
		}
	}

	conn, err := prepareConnection()
	if err != nil {
		t.Fatal(err)
	}
	if conn.Servers != "tls://imre:4222" || !conn.E2E || conn.KeyFile != key || conn.CA != ca {
		t.Fatalf("conn=%+v", conn)
	}

	if err := runConfigSet(newConfigSetCommand(), []string{"nats_servers", "tls://imre:4223"}); err == nil || !strings.Contains(err.Error(), "unknown config key") {
		t.Fatalf("config set nats_servers error=%v", err)
	}
	if err := setActiveProfileField("nats_servers", "nats://nope:4222"); err == nil {
		t.Fatal("expected profile set scheme mismatch")
	}
	if err := setActiveProfileField("nats_servers", "tls://imre:4223"); err != nil {
		t.Fatal(err)
	}
	activeName := ""
	if cfg, err := puda.LoadGlobalConfig(); err != nil {
		t.Fatal(err)
	} else {
		activeName = cfg.ActiveProfile
	}
	if activeName != "imre" {
		t.Fatalf("profile set changed the active profile to %q", activeName)
	}

	listCmd := &cobra.Command{}
	listCmd.SetOut(&bytes.Buffer{})
	if err := runConfigList(listCmd, nil); err != nil {
		t.Fatal(err)
	}
	configList := listCmd.OutOrStdout().(*bytes.Buffer).String()
	if strings.Contains(configList, "nats_servers=") || strings.Contains(configList, "e2e=") || !strings.Contains(configList, "user.username=zhao\n") {
		t.Fatalf("config list=%q", configList)
	}

	saved, err := puda.LoadGlobalConfig()
	if err != nil {
		t.Fatal(err)
	}
	if saved.Profiles["imre"].NATSServers != "tls://imre:4223" {
		t.Fatalf("profile servers=%q", saved.Profiles["imre"].NATSServers)
	}

	if err := removeProfile("imre"); err != nil {
		t.Fatal(err)
	}
	if err := printCurrentProfile(&bytes.Buffer{}, false); err == nil {
		t.Fatal("expected no active profile after removing it")
	}
	if _, err = prepareConnection(); err == nil {
		t.Fatal("expected missing profile to be rejected")
	}
}

func TestEncryptionOffForPlainProfile(t *testing.T) {
	t.Cleanup(pudanats.ResetSession)
	setupGlobalConfig(t, puda.GlobalConfig{
		User: puda.ConfigUser{Username: "zhao", UserID: "generated-id"},
	})
	if _, err := addProfile("bears", "nats://bears:4222", "", "", ""); err != nil {
		t.Fatal(err)
	}
	err := requireEncryption()
	if err == nil || !strings.Contains(err.Error(), `profile "bears"`) || !strings.Contains(err.Error(), e2eSetupDocs) {
		t.Fatalf("error=%v", err)
	}
}

func writeProfileMaterial(t *testing.T) (string, string) {
	t.Helper()
	dir := t.TempDir()
	ca := filepath.Join(dir, "ca.pem")
	key := filepath.Join(dir, "e2e.key")
	if err := os.WriteFile(ca, []byte("ca"), 0o600); err != nil {
		t.Fatal(err)
	}
	body := "encrypt=" + base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{0x11}, 32)) + "\n"
	if err := os.WriteFile(key, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return ca, key
}
