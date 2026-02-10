package puda

import (
	"fmt"
	"os"
	"path/filepath"
)

// ConfigPath returns the path to the PUDA configuration file.
//
// Preference order:
//  1. XDG / OS-specific config directory (os.UserConfigDir), e.g.:
//     - Linux:   ~/.config/puda/config.json
//     - macOS:   ~/Library/Application Support/puda/config.json
//     - Windows: %AppData%\\puda\\config.json
//  2. Legacy location in the home directory: ~/.puda/config.json
//
// If a legacy config file exists and the new location does not, the legacy
// path is returned to avoid breaking existing installations.
func ConfigPath() (string, error) {
	// Try OS-specific user config directory first.
	if base, err := os.UserConfigDir(); err == nil && base != "" {
		newDir := filepath.Join(base, "puda")
		newPath := filepath.Join(newDir, "config.json")

		// If a legacy file exists but the new one doesn't, keep using legacy.
		if home, err := os.UserHomeDir(); err == nil && home != "" {
			legacyPath := filepath.Join(home, ".puda", "config.json")
			if _, err := os.Stat(legacyPath); err == nil {
				return legacyPath, nil
			}
		}

		return newPath, nil
	}

	// Fallback: use legacy location in the home directory.
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("failed to determine home directory: %w", err)
	}
	return filepath.Join(homeDir, ".puda", "config.json"), nil
}
