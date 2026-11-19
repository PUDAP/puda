package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func writeSkill(t *testing.T, dir, name string) string {
	t.Helper()
	skill := filepath.Join(dir, name)
	if err := os.MkdirAll(skill, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(skill, "SKILL.md"), []byte("---\nname: "+name+"\ndescription: test\n---\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return skill
}

// skillsLinkEnv isolates HOME and HERMES_HOME so tests never touch real agents.
func skillsLinkEnv(t *testing.T) (home, hermes string) {
	t.Helper()
	home = t.TempDir()
	hermes = filepath.Join(home, "hermes-home")
	if err := os.MkdirAll(hermes, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("HOME", home)
	t.Setenv("HERMES_HOME", hermes)
	return home, hermes
}

func runInstallCapture(t *testing.T, args []string) (string, error) {
	t.Helper()
	var out bytes.Buffer
	skillsInstallCmd.SetOut(&out)
	t.Cleanup(func() { skillsInstallCmd.SetOut(nil) })
	err := runSkillsInstall(skillsInstallCmd, args)
	return out.String(), err
}

func assertLink(t *testing.T, target, want string) {
	t.Helper()
	got, err := os.Readlink(target)
	if err != nil {
		t.Fatalf("%s is not a symlink: %v", target, err)
	}
	if got != want {
		t.Fatalf("%s -> %s; want %s", target, got, want)
	}
}

func TestSkillsInstallSymlinksMonorepoSkills(t *testing.T) {
	calls := captureSkillsNpx(t)
	home, hermes := skillsLinkEnv(t)
	repo := t.TempDir()
	alpha := writeSkill(t, filepath.Join(repo, "skills"), "alpha")
	beta := writeSkill(t, filepath.Join(repo, "skills"), "beta")
	if err := os.MkdirAll(filepath.Join(repo, "edges", "robot"), 0o755); err != nil {
		t.Fatal(err)
	}

	for _, source := range []string{repo, filepath.Join(repo, "skills")} {
		out, err := runInstallCapture(t, []string{source})
		if err != nil {
			t.Fatalf("%s: %v", source, err)
		}
		shared := filepath.Join(home, ".agents", "skills")
		assertLink(t, filepath.Join(shared, "alpha"), alpha)
		assertLink(t, filepath.Join(shared, "beta"), beta)
		assertLink(t, filepath.Join(hermes, "skills", "alpha"), filepath.Join(shared, "alpha"))
		if _, err := os.Lstat(filepath.Join(home, ".claude", "skills")); !os.IsNotExist(err) {
			t.Fatalf("linked into an agent that is not installed: %v", err)
		}
		if !strings.Contains(out, "symlinked "+filepath.Join(shared, "alpha")+" -> "+alpha) || !strings.Contains(out, "Symlinked 2 local skill(s)") {
			t.Fatalf("output = %q", out)
		}
	}
	// Local sources never reach npx; only the official default does.
	want := []string{
		"skills add https://github.com/PUDAP/puda/tree/v0.1.6/skills -y -g",
		"skills add https://github.com/PUDAP/puda/tree/v0.1.6/skills -y -g",
	}
	if got := calls(); !reflect.DeepEqual(got, want) {
		t.Fatalf("npx calls = %q; want %q", got, want)
	}

	// Edits through the agent path land in the repository.
	if err := os.WriteFile(filepath.Join(hermes, "skills", "alpha", "SKILL.md"), []byte("edited"), 0o644); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(filepath.Join(alpha, "SKILL.md")); string(b) != "edited" {
		t.Fatalf("repo skill = %q", b)
	}
}

func TestSkillsInstallKeepsCopiedFolders(t *testing.T) {
	captureSkillsNpx(t)
	home, _ := skillsLinkEnv(t)
	repo := t.TempDir()
	writeSkill(t, filepath.Join(repo, "skills"), "alpha")
	beta := writeSkill(t, filepath.Join(repo, "skills"), "beta")
	copied := writeSkill(t, filepath.Join(home, ".agents", "skills"), "alpha")

	out, err := runInstallCapture(t, []string{repo})
	if err == nil || !strings.Contains(err.Error(), copied) || !strings.Contains(err.Error(), "not a symlink") {
		t.Fatalf("expected conflict error, got %v", err)
	}
	if info, err := os.Lstat(copied); err != nil || info.Mode()&os.ModeSymlink != 0 {
		t.Fatalf("copied folder was replaced: %v", err)
	}
	assertLink(t, filepath.Join(home, ".agents", "skills", "beta"), beta)
	if !strings.Contains(out, "Symlinked 1 local skill(s)") {
		t.Fatalf("output = %q", out)
	}
}

func TestSkillsInstallRejectsBadLocalPathsBeforeNpx(t *testing.T) {
	calls := captureSkillsNpx(t)
	skillsLinkEnv(t)
	empty := t.TempDir()
	for _, arg := range []string{"./does-not-exist", "/does/not/exist", "~/does-not-exist", empty} {
		if _, err := runInstallCapture(t, []string{arg}); err == nil {
			t.Fatalf("%s: expected error", arg)
		}
	}
	if got := calls(); len(got) != 0 {
		t.Fatalf("bad local path invoked npx: %q", got)
	}
}

func TestSkillsInstallLinksSingleSkillFolder(t *testing.T) {
	captureSkillsNpx(t)
	home, _ := skillsLinkEnv(t)
	skill := writeSkill(t, t.TempDir(), "solo")
	if _, err := runInstallCapture(t, []string{skill}); err != nil {
		t.Fatal(err)
	}
	assertLink(t, filepath.Join(home, ".agents", "skills", "solo"), skill)
}
