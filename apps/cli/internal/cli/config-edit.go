package cli

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// lookPath is exec.LookPath, swapped in tests.
var lookPath = exec.LookPath

// configEditCmd opens the PUDA configuration file in the user's default editor.
var configEditCmd = &cobra.Command{
	Use:   "edit",
	Short: "Edit PUDA CLI configuration",
	Long: `Open the PUDA CLI configuration file in a terminal editor.

Uses $EDITOR, then $VISUAL, then a terminal editor on PATH (editor, nano, vim, or vi).
On Windows, notepad is used when no editor environment variable is set.`,
	RunE: runConfigEdit,
}

// runConfigEdit ensures the config file exists and opens it in an editor.
func runConfigEdit(cmd *cobra.Command, args []string) error {
	configPath, err := puda.GlobalConfigPath()
	if err != nil {
		return err
	}

	configDir := filepath.Dir(configPath)
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		return fmt.Errorf("failed to create config directory %s: %w", configDir, err)
	}

	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		return fmt.Errorf("no configuration found; run 'puda login' first")
	} else if err != nil {
		return fmt.Errorf("failed to stat config file %s: %w", configPath, err)
	}

	fmt.Fprintf(cmd.OutOrStdout(), "Opening %s\n", configPath)
	if err := openInEditor(configPath); err != nil {
		return fmt.Errorf("failed to open editor: %w", err)
	}

	return nil
}

func resolveEditor() (name string, extraArgs []string, err error) {
	for _, env := range []string{"EDITOR", "VISUAL"} {
		if v := strings.TrimSpace(os.Getenv(env)); v != "" {
			fields := strings.Fields(v)
			return fields[0], fields[1:], nil
		}
	}

	candidates := []string{"editor", "nano", "vim", "vi"}
	if runtime.GOOS == "windows" {
		candidates = append(candidates, "notepad")
	}
	for _, name := range candidates {
		path, lookErr := lookPath(name)
		if lookErr == nil {
			return path, nil, nil
		}
	}

	return "", nil, fmt.Errorf("no editor found; set the EDITOR environment variable")
}

// openInEditor opens the given file in the user's preferred or OS-default editor.
func openInEditor(path string) error {
	name, extraArgs, err := resolveEditor()
	if err != nil {
		return err
	}

	args := append(append([]string{}, extraArgs...), path)
	c := exec.Command(name, args...)
	c.Stdin = os.Stdin
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr
	return c.Run()
}
