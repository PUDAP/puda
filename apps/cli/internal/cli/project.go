package cli

import "github.com/spf13/cobra"

// projectCmd is the parent command for project-related operations.
var projectCmd = &cobra.Command{
	Use:   "project",
	Short: "Project operations",
	Long: `Commands for working with a project.

Project settings are 'puda project config'.`,
}

// init registers all project subcommands.
func init() {
	projectCmd.AddCommand(projectHashCmd)
}
