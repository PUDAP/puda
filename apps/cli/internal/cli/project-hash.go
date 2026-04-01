package cli

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

var (
	projectID     string
	projectDBPath string
)

// projectHashCmd hashes the extracted relational project data for a project ID.
var projectHashCmd = &cobra.Command{
	Use:   "hash",
	Short: "Hash project data",
	Long: `Hash project-linked protocol, run, sample, and measurement data.

This command extracts the normalized project dataset from the local database and
returns a deterministic SHA-256 hash for the result set.

Example:
  puda project hash --id <project_id>
  puda project hash --id <project_id> --db ./puda.db`,
	Args: cobra.NoArgs,
	RunE: runProjectHash,
}

func runProjectHash(cmd *cobra.Command, args []string) error {
	store, err := db.Connect(projectDBPath)
	if err != nil {
		return fmt.Errorf("failed to connect to database: %w", err)
	}
	defer store.Disconnect()

	var dbPath string
	if projectDBPath != "" {
		dbPath = projectDBPath
	} else {
		cfg, err := puda.LoadProjectConfig()
		if err != nil {
			return fmt.Errorf("failed to load project config: %w", err)
		}
		dbPath = cfg.Database.Path
	}

	hash, err := puda.GetProjectHash(dbPath)
	if err != nil {
		return fmt.Errorf("failed to hash project data: %w", err)
	}

	response := map[string]string{
		"project_id": projectID,
		"file_path":  filepath.Base(dbPath),
		"hash":       hash,
		"timestamp":  time.Now().Format(time.RFC3339),
	}

	jsonOutput, err := json.MarshalIndent(response, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}

	fmt.Fprintln(cmd.OutOrStdout(), string(jsonOutput))
	return nil
}

func init() {
	projectHashCmd.Flags().StringVar(&projectID, "id", "", "Project ID (required)")
	projectHashCmd.Flags().StringVar(&projectDBPath, "db", "", "Optional database path (relative or absolute)")
	projectHashCmd.MarkFlagRequired("id")
}
