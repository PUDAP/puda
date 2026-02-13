package puda

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// GlobalConfigPath returns the path to the main/global PUDA configuration file.
//
// The config file is always stored in the OS-specific user config directory:
//   - Linux:   ~/.config/puda/config.json
//   - macOS:   ~/Library/Application Support/puda/config.json
//   - Windows: %AppData%\\puda\\config.json
//
// The directory is created if it doesn't exist.
func GlobalConfigPath() (string, error) {
	base, err := os.UserConfigDir()
	if err != nil {
		return "", fmt.Errorf("failed to determine user config directory: %w", err)
	}
	if base == "" {
		return "", fmt.Errorf("user config directory is empty")
	}

	configDir := filepath.Join(base, "puda")
	configPath := filepath.Join(configDir, "config.json")

	// Ensure the directory exists before returning the path
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		return "", fmt.Errorf("failed to create config directory %s: %w", configDir, err)
	}

	return configPath, nil
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
// If the config file is found, its directory is ensured to exist before returning.
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
			// Ensure the directory exists before returning the path
			configDir := filepath.Dir(configPath)
			if err := os.MkdirAll(configDir, 0755); err != nil {
				return "", fmt.Errorf("failed to create config directory %s: %w", configDir, err)
			}
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
