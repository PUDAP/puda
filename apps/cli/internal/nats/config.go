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
// Returns userID, username, natsServers, error
// USER_ID and USERNAME are optional (can be provided in JSON file instead)
// NATS_SERVERS is required
func LoadEnvConfig() (string, string, string, error) {
	// Try to load .env file from current directory or project root
	envPath := ".env"
	if _, err := os.Stat(envPath); os.IsNotExist(err) {
		// Try parent directory (project root)
		envPath = filepath.Join("..", "..", ".env")
		if _, err := os.Stat(envPath); os.IsNotExist(err) {
			return "", "", "", fmt.Errorf("no .env file found. Please create a .env file in the project root with NATS_SERVERS variable")
		}
	}

	if err := godotenv.Load(envPath); err != nil {
		return "", "", "", fmt.Errorf("failed to load .env file: %w", err)
	}

	envUserID := os.Getenv("USER_ID")
	envUsername := os.Getenv("USERNAME")
	envNatsServers := os.Getenv("NATS_SERVERS")

	if envNatsServers == "" {
		return "", "", "", fmt.Errorf("NATS_SERVERS is required in .env file")
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
