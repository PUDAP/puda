package cli

import (
	"errors"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestResolveEditorPrefersEDITOR(t *testing.T) {
	t.Setenv("EDITOR", "nano -w")
	t.Setenv("VISUAL", "vim")

	name, args, err := resolveEditor()
	if err != nil {
		t.Fatal(err)
	}
	if name != "nano" {
		t.Fatalf("name=%q, want nano", name)
	}
	if len(args) != 1 || args[0] != "-w" {
		t.Fatalf("args=%v, want [-w]", args)
	}
}

func TestResolveEditorUsesVISUALWhenEDITOREmpty(t *testing.T) {
	t.Setenv("EDITOR", "  ")
	t.Setenv("VISUAL", "vim")

	name, args, err := resolveEditor()
	if err != nil {
		t.Fatal(err)
	}
	if name != "vim" {
		t.Fatalf("name=%q, want vim", name)
	}
	if len(args) != 0 {
		t.Fatalf("args=%v, want empty", args)
	}
}

func TestResolveEditorFallsBackToPATH(t *testing.T) {
	t.Setenv("EDITOR", "")
	t.Setenv("VISUAL", "")
	t.Cleanup(func() { lookPath = exec.LookPath })

	lookPath = func(file string) (string, error) {
		if file == "nano" {
			return "/usr/bin/nano", nil
		}
		return "", errors.New("not found")
	}

	name, args, err := resolveEditor()
	if err != nil {
		t.Fatal(err)
	}
	if name != "/usr/bin/nano" {
		t.Fatalf("name=%q, want /usr/bin/nano", name)
	}
	if len(args) != 0 {
		t.Fatalf("args=%v, want empty", args)
	}
}

func TestResolveEditorErrorsWhenNoneFound(t *testing.T) {
	t.Setenv("EDITOR", "")
	t.Setenv("VISUAL", "")
	t.Cleanup(func() { lookPath = exec.LookPath })

	lookPath = func(file string) (string, error) {
		return "", errors.New("not found: " + file)
	}

	_, _, err := resolveEditor()
	if err == nil {
		t.Fatal("expected error when no editor is available")
	}
}

func TestRunConfigEditRequiresLogin(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
	t.Setenv("AppData", home)

	err := runConfigEdit(newConfigSetCommand(), nil)
	if err == nil || err.Error() != "no configuration found; run 'puda login' first" {
		t.Fatalf("error=%v", err)
	}
}
