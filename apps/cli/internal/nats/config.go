package nats

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/joho/godotenv"
)

// Config holds the configuration for NATS operations
type Config struct {
	UserID      string
	Username    string
	NATSServers []string
}

// LoadEnvConfig loads configuration from .env file
func LoadEnvConfig() (string, string, string, error) {
	// Try to load .env file from current directory or project root
	envPath := ".env"
	if _, err := os.Stat(envPath); os.IsNotExist(err) {
		// Try parent directory (project root)
		envPath = filepath.Join("..", "..", ".env")
		if _, err := os.Stat(envPath); os.IsNotExist(err) {
			return "", "", "", fmt.Errorf("no .env file found. Please create a .env file in the project root with USER_ID, USERNAME, and NATS_SERVERS variables")
		}
	}

	if err := godotenv.Load(envPath); err != nil {
		return "", "", "", fmt.Errorf("failed to load .env file: %w", err)
	}

	envUserID := os.Getenv("USER_ID")
	envUsername := os.Getenv("USERNAME")
	envNatsServers := os.Getenv("NATS_SERVERS")

	missing := []string{}
	if envUserID == "" {
		missing = append(missing, "USER_ID")
	}
	if envUsername == "" {
		missing = append(missing, "USERNAME")
	}
	if envNatsServers == "" {
		missing = append(missing, "NATS_SERVERS")
	}

	if len(missing) > 0 {
		return "", "", "", fmt.Errorf("missing required environment variables in .env file: %s", strings.Join(missing, ", "))
	}

	return envUserID, envUsername, envNatsServers, nil
}

// ParseNATSServers parses a comma-separated string of NATS server URLs
func ParseNATSServers(serversStr string) []string {
	servers := strings.Split(serversStr, ",")
	result := make([]string, 0, len(servers))
	for _, s := range servers {
		s = strings.TrimSpace(s)
		if s != "" {
			result = append(result, s)
		}
	}
	return result
}
