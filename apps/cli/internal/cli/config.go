package cli

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

// configCmd opens the PUDA configuration file in the user's default editor.
//
// The configuration file is located at:
//
//	~/.puda/config.json
//
// On first run, the file will be created if it does not exist.
var configCmd = &cobra.Command{
	Use:   "config",
	Short: "Edit PUDA CLI configuration",
	Long: `Open the PUDA CLI configuration file in your default editor.

If the configuration file does not exist, a minimal template will be created.

On Unix-like systems, the EDITOR or VISUAL environment variable is used when set.
Otherwise, the OS default application for JSON files is used.`,
	RunE: runConfigEdit,
}

// runConfigEdit ensures the config file exists and opens it in an editor.
func runConfigEdit(cmd *cobra.Command, args []string) error {
	configPath, err := puda.ConfigPath()
	if err != nil {
		return err
	}

	configDir := filepath.Dir(configPath)
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		return fmt.Errorf("failed to create config directory %s: %w", configDir, err)
	}

	// If the config file does not exist, instruct the user to run `puda login`
	// instead of silently creating a new file, so that required fields like
	// user ID are properly initialized.
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		fmt.Fprintln(cmd.OutOrStdout(), "No configuration found.")
		fmt.Fprintln(cmd.OutOrStdout(), "Please run `puda login` first to create your configuration file.")
		return nil
	}

	if err := openInEditor(configPath); err != nil {
		return fmt.Errorf("failed to open editor: %w", err)
	}

	return nil
}

// openInEditor opens the given file in the user's preferred or OS-default editor.
func openInEditor(path string) error {
	// Prefer explicit editor configuration
	if editor := os.Getenv("EDITOR"); editor != "" {
		c := exec.Command(editor, path)
		c.Stdin = os.Stdin
		c.Stdout = os.Stdout
		c.Stderr = os.Stderr
		return c.Run()
	}
	if visual := os.Getenv("VISUAL"); visual != "" {
		c := exec.Command(visual, path)
		c.Stdin = os.Stdin
		c.Stdout = os.Stdout
		c.Stderr = os.Stderr
		return c.Run()
	}

	// Fallback to OS-specific default opener
	switch runtime.GOOS {
	case "windows":
		// Use "start" via cmd.exe, with empty title argument
		c := exec.Command("cmd", "/c", "start", "", path)
		c.Stdin = os.Stdin
		c.Stdout = os.Stdout
		c.Stderr = os.Stderr
		return c.Run()
	case "darwin":
		c := exec.Command("open", path)
		c.Stdin = os.Stdin
		c.Stdout = os.Stdout
		c.Stderr = os.Stderr
		return c.Run()
	default:
		// Most Linux/BSD desktops support xdg-open
		c := exec.Command("xdg-open", path)
		c.Stdin = os.Stdin
		c.Stdout = os.Stdout
		c.Stderr = os.Stderr
		return c.Run()
	}
}
