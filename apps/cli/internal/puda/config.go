package puda

import (
	"encoding/json"
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

// LoadConfig loads the PUDA configuration file and returns it as a PUDAConfig.
func LoadConfig() (*PUDAConfig, error) {
	configPath, err := ConfigPath()
	if err != nil {
		return nil, fmt.Errorf("failed to determine PUDA config path: %w", err)
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("PUDA config file not found at %s. Please run 'puda login' to create it", configPath)
		}
		return nil, fmt.Errorf("failed to read PUDA config file %s: %w", configPath, err)
	}

	var fileCfg PUDAConfig
	if err := json.Unmarshal(data, &fileCfg); err != nil {
		return nil, fmt.Errorf("failed to parse PUDA config file %s: %w", configPath, err)
	}

	// Validate that all required values are present
	if fileCfg.User.Username == "" {
		return nil, fmt.Errorf("username is missing in PUDA config file %s", configPath)
	}
	if fileCfg.User.UserID == "" {
		return nil, fmt.Errorf("user ID is missing in PUDA config file %s", configPath)
	}
	if fileCfg.Endpoints.NATS == "" {
		return nil, fmt.Errorf("NATS endpoint is missing in PUDA config file %s", configPath)
	}

	return &fileCfg, nil
}
