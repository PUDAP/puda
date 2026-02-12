package puda

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// GlobalConfigPath returns the path to the main/global PUDA configuration file.
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
func GlobalConfigPath() (string, error) {
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

// loadGlobalConfigFromPath loads a global PUDA configuration file from the specified path.
func loadGlobalConfigFromPath(configPath string) (*GlobalConfig, error) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("PUDA config file not found at %s. Please run 'puda login' to create it", configPath)
		}
		return nil, fmt.Errorf("failed to read PUDA config file %s: %w", configPath, err)
	}

	var fileCfg GlobalConfig
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

	return &fileCfg, nil
}

// loadProjectConfigFromPath loads a project PUDA configuration file from the specified path.
func loadProjectConfigFromPath(configPath string) (*ProjectConfig, error) {
	data, err := os.ReadFile(configPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("PUDA config file not found at %s. Please run 'puda init' to create it", configPath)
		}
		return nil, fmt.Errorf("failed to read PUDA config file %s: %w", configPath, err)
	}

	var fileCfg ProjectConfig
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

	return &fileCfg, nil
}

// LoadGlobalConfig loads the main/global PUDA configuration file and returns it as a GlobalConfig.
func LoadGlobalConfig() (*GlobalConfig, error) {
	configPath, err := GlobalConfigPath()
	if err != nil {
		return nil, fmt.Errorf("failed to determine PUDA config path: %w", err)
	}

	return loadGlobalConfigFromPath(configPath)
}

// ProjectConfigPath returns the path to the project-level puda.config file.
// It recursively searches for puda.config starting from the current directory and walking up the directory tree.
func ProjectConfigPath() (string, error) {
	// Start from current working directory
	dir, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("failed to get current directory: %w", err)
	}

	// Walk up the directory tree looking for puda.config
	for {
		configPath := filepath.Join(dir, "puda.config")
		if _, err := os.Stat(configPath); err == nil {
			return configPath, nil
		}

		// Move up one directory
		parent := filepath.Dir(dir)
		if parent == dir {
			// Reached root, config not found
			return "", nil
		}
		dir = parent
	}
}

// LoadProjectConfig loads the project-level puda.config file and returns it as a ProjectConfig.
// If the project config is not found, it returns an error.
func LoadProjectConfig() (*ProjectConfig, error) {
	configPath, err := ProjectConfigPath()
	if err != nil {
		return nil, fmt.Errorf("failed to determine project config path: %w", err)
	}

	// Check if file exists first
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		return nil, fmt.Errorf("puda.config not found in current directory. Please run 'puda init' to create it")
	}

	return loadProjectConfigFromPath(configPath)
}
