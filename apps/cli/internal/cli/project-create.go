package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/spf13/cobra"
)

var (
	projectID          string
	projectName        string
	projectDescription string
)

// projectCreateCmd creates a new project record in the database.
var projectCreateCmd = &cobra.Command{
	Use:   "create",
	Short: "Create a new project",
	Long: `Create a new project in the PUDA database.

Example:
  puda project create --id proj-001 --name "Test Project" --description "Initial project"`,
	Args: cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		store, err := db.Connect()
		if err != nil {
			return fmt.Errorf("failed to connect to database: %w", err)
		}
		defer store.Disconnect()

		if err := store.InsertProject(projectID, projectName, projectDescription); err != nil {
			return err
		}

		fmt.Fprintf(os.Stdout, "Project created: %s\n", projectID)
		return nil
	},
}

func init() {
	projectCreateCmd.Flags().StringVar(&projectID, "id", "", "Project ID (required)")
	projectCreateCmd.Flags().StringVar(&projectName, "name", "", "Project name (required)")
	projectCreateCmd.Flags().StringVar(&projectDescription, "description", "", "Project description")
	projectCreateCmd.MarkFlagRequired("id")
	projectCreateCmd.MarkFlagRequired("name")
}
