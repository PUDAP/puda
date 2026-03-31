package cli

import (
	"encoding/json"
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

var (
	projectHashID     string
	projectHashDBPath string
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
	store, err := db.Connect(projectHashDBPath)
	if err != nil {
		return fmt.Errorf("failed to connect to database: %w", err)
	}
	defer store.Disconnect()

	outputPath, err := store.ExportProject(projectHashID)
	if err != nil {
		return fmt.Errorf("failed to extract project data: %w", err)
	}

	hash, err := puda.GetProjectHash(outputPath)
	if err != nil {
		return fmt.Errorf("failed to hash project data: %w", err)
	}

	response := map[string]string{
		"status":      "success",
		"project_id":  projectHashID,
		"output_path": outputPath,
		"hash":        hash,
	}

	jsonOutput, err := json.MarshalIndent(response, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}

	fmt.Fprintln(cmd.OutOrStdout(), string(jsonOutput))
	return nil
}

func init() {
	projectHashCmd.Flags().StringVar(&projectHashID, "id", "", "Project ID (required)")
	projectHashCmd.Flags().StringVar(&projectHashDBPath, "db", "", "Database path (relative or absolute)")
	projectHashCmd.MarkFlagRequired("id")
}
