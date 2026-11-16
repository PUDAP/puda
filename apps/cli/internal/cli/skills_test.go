package cli

import (
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

// Exercise the real subprocess boundary without network or agent-profile writes.
func captureSkillsNpx(t *testing.T) func() []string {
	t.Helper()
	dir := t.TempDir()
	log := filepath.Join(dir, "calls")
	if err := os.WriteFile(filepath.Join(dir, "npx"), []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$SKILLS_TEST_LOG\"\n"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir)
	t.Setenv("SKILLS_TEST_LOG", log)
	old := Version
	Version = "0.1.6"
	t.Cleanup(func() { Version = old })
	return func() []string {
		b, err := os.ReadFile(log)
		if os.IsNotExist(err) {
			return nil
		}
		if err != nil {
			t.Fatal(err)
		}
		return strings.Split(strings.TrimSpace(string(b)), "\n")
	}
}

func TestSkillsExplicitRefsAndCustomStreamlit(t *testing.T) {
	for _, command := range []*cobra.Command{skillsInstallCmd, skillsUpdateCmd} {
		for _, ref := range []string{"main", "v0.1.6", "0.1.6", "v0.1.6-rc1", "feature-name"} {
			t.Run(command.Name()+"/"+ref, func(t *testing.T) {
				calls := captureSkillsNpx(t)
				Version = "dev"
				if err := command.Flags().Set("ref", ref); err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() { _ = command.Flags().Set("ref", ""); command.Flags().Lookup("ref").Changed = false })
				if err := command.RunE(command, []string{"streamlit/agent-skills"}); err != nil {
					t.Fatal(err)
				}
				want := []string{"skills add https://github.com/PUDAP/puda/tree/" + ref + "/skills -y -g", "skills add streamlit/agent-skills -y -g"}
				if got := calls(); !reflect.DeepEqual(got, want) {
					t.Fatalf("calls = %q; want %q", got, want)
				}
			})
		}
	}
}

func TestSkillsInvalidRefsNeverInvokeNpx(t *testing.T) {
	for _, command := range []*cobra.Command{skillsInstallCmd, skillsUpdateCmd} {
		for _, ref := range []string{"", "../main", "feature/name", " main", "main ", "main\n", "main?x", "main#x", "main%2Fother", "-main", ".main", "main..other", "main.", "main.lock", "main@{1}", "main\\other"} {
			t.Run(command.Name()+"/"+ref, func(t *testing.T) {
				calls := captureSkillsNpx(t)
				if err := command.ParseFlags([]string{"--ref=" + ref}); err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() { _ = command.Flags().Set("ref", ""); command.Flags().Lookup("ref").Changed = false })
				if err := command.RunE(command, nil); err == nil || !strings.Contains(err.Error(), "ref") {
					t.Fatalf("expected invalid ref error, got %v", err)
				}
				if got := calls(); len(got) != 0 {
					t.Fatalf("invalid ref invoked npx: %q", got)
				}
			})
		}
	}
}

func TestSkillsMainFlagRemoved(t *testing.T) {
	for _, command := range []*cobra.Command{skillsInstallCmd, skillsUpdateCmd} {
		if err := command.ParseFlags([]string{"--main"}); err == nil {
			t.Fatal("obsolete --main accepted")
		}
	}
}

func TestSkillsDevelopmentRequiresExplicitRef(t *testing.T) {
	for _, version := range []string{"dev", "dev-abcdef-dirty", "", "(devel)", "0.1.6-SNAPSHOT-abc", "0.1.6-0.20261116000000-abcdef123456"} {
		t.Run(version, func(t *testing.T) {
			calls := captureSkillsNpx(t)
			Version = version
			err := runSkillsInstall(skillsInstallCmd, nil)
			if err == nil || !strings.Contains(err.Error(), "--ref main") {
				t.Fatalf("expected explicit --ref main guidance, got %v", err)
			}
			if got := calls(); len(got) != 0 {
				t.Fatalf("development install ran npx: %q", got)
			}
		})
	}
}

func TestSkillsMainIsExplicitForDevelopment(t *testing.T) {
	calls := captureSkillsNpx(t)
	Version = "dev-dirty"
	if err := skillsInstallCmd.Flags().Set("ref", "main"); err != nil {
		t.Fatalf("missing --ref main: %v", err)
	}
	t.Cleanup(func() {
		_ = skillsInstallCmd.Flags().Set("ref", "")
		skillsInstallCmd.Flags().Lookup("ref").Changed = false
	})
	if err := runSkillsInstall(skillsInstallCmd, nil); err != nil {
		t.Fatal(err)
	}
	if got := calls(); len(got) != 1 || got[0] != "skills add https://github.com/PUDAP/puda/tree/main/skills -y -g" {
		t.Fatalf("main calls = %q", got)
	}
}

func TestSkillsUpdateReaddsReleaseToMigrateLegacyLock(t *testing.T) {
	calls := captureSkillsNpx(t)
	// A legacy global lock must not cause a broad update against PUDAP/skills.
	home := t.TempDir()
	t.Setenv("HOME", home)
	if err := os.MkdirAll(filepath.Join(home, ".agents"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agents", ".skill-lock.json"), []byte(`{"version":3,"skills":{"puda":{"source":"PUDAP/skills"}}}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err := runSkillsUpdate(skillsUpdateCmd, []string{"owner/custom#stable"}); err != nil {
		t.Fatal(err)
	}
	want := []string{"skills add https://github.com/PUDAP/puda/tree/v0.1.6/skills -y -g", "skills add owner/custom#stable -y -g"}
	if got := calls(); !reflect.DeepEqual(got, want) {
		t.Fatalf("migration calls = %q; want %q", got, want)
	}
}

func TestSkillsReleaseVersionsAndCustomSources(t *testing.T) {
	for _, version := range []string{"v0.1.6", "0.1.6", "v0.1.6-rc1"} {
		t.Run(version, func(t *testing.T) {
			calls := captureSkillsNpx(t)
			Version = version
			custom := "https://github.com/example/custom/tree/stable/skills"
			if err := runSkillsInstall(skillsInstallCmd, []string{custom}); err != nil {
				t.Fatal(err)
			}
			want := []string{"skills add https://github.com/PUDAP/puda/tree/v" + strings.TrimPrefix(version, "v") + "/skills -y -g", "skills add " + custom + " -y -g"}
			if got := calls(); !reflect.DeepEqual(got, want) {
				t.Fatalf("calls = %q; want %q", got, want)
			}
		})
	}
}

func TestSkillsUpdateMainAndDevelopmentDefault(t *testing.T) {
	calls := captureSkillsNpx(t)
	Version = "dev"
	if err := runSkillsUpdate(skillsUpdateCmd, nil); err == nil {
		t.Fatal("development default should fail")
	}
	if len(calls()) != 0 {
		t.Fatal("development default invoked npx")
	}
	if err := skillsUpdateCmd.ParseFlags([]string{"--ref", "main"}); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_ = skillsUpdateCmd.Flags().Set("ref", "")
		skillsUpdateCmd.Flags().Lookup("ref").Changed = false
	})
	if err := runSkillsUpdate(skillsUpdateCmd, nil); err != nil {
		t.Fatal(err)
	}
	if got := calls(); len(got) != 1 || got[0] != "skills add https://github.com/PUDAP/puda/tree/main/skills -y -g" {
		t.Fatalf("calls = %q", got)
	}
}

func TestSkillsFailedPinnedAddStopsWithoutFallback(t *testing.T) {
	calls := captureSkillsNpx(t)
	npx := filepath.Join(os.Getenv("PATH"), "npx")
	if err := os.WriteFile(npx, []byte("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$SKILLS_TEST_LOG\"\nexit 1\n"), 0700); err != nil {
		t.Fatal(err)
	}
	err := runSkillsInstall(skillsInstallCmd, nil)
	if err == nil || !strings.Contains(err.Error(), "v0.1.6/skills") {
		t.Fatalf("error = %v", err)
	}
	if got := calls(); len(got) != 1 {
		t.Fatalf("failure ran extra commands: %q", got)
	}
}

func TestSkillsInstallPinsReleaseWithoutBroadUpdate(t *testing.T) {
	calls := captureSkillsNpx(t)
	skillsInstallCmd.SetOut(io.Discard)
	if err := runSkillsInstall(skillsInstallCmd, nil); err != nil {
		t.Fatal(err)
	}
	want := []string{
		"skills add https://github.com/PUDAP/puda/tree/v0.1.6/skills -y -g",
	}
	if got := calls(); !reflect.DeepEqual(got, want) {
		t.Fatalf("npx calls = %q; want %q", got, want)
	}
}
