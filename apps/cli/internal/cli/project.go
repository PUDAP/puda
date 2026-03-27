package cli

import "github.com/spf13/cobra"

// projectCmd is the parent command for project-related operations.
var projectCmd = &cobra.Command{
	Use:   "project",
	Short: "Project operations",
	Long: `Commands for working with projects.

For help on subcommands, add --help after: "puda project create --help"`,
}

// init registers all project subcommands.
func init() {
	projectCmd.AddCommand(projectCreateCmd)
}
