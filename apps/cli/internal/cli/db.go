package cli

import "github.com/spf13/cobra"

// dbCmd is the top-level command for database-related operations
//
// Subcommands:
//   - exec: Execute SQL commands on the database
//   - schema: Display the database schema
var dbCmd = &cobra.Command{
	Use:   "db",
	Short: "Database operations",
	Long: `Commands for interacting with the PUDA database.

For help on subcommands, add --help after: "puda db exec --help"`,
}

// init registers all database subcommands
func init() {
	dbCmd.AddCommand(dbExecCmd)
	dbCmd.AddCommand(dbSchemaCmd)
}
