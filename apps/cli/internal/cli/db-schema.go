package cli

import (
	"fmt"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/spf13/cobra"
)

// dbSchemaCmd displays the database schema
var dbSchemaCmd = &cobra.Command{
	Use:   "schema",
	Short: "Display the database schema",
	Long: `Display the complete database schema (SQL DDL statements).

This command prints the initialization SQL script that defines all tables,
indexes, and constraints in the PUDA database.

Example:
  puda db schema`,
	RunE: runDbSchema,
}

// runDbSchema displays the database schema
func runDbSchema(cmd *cobra.Command, args []string) error {
	schema := db.GetInitSQL()
	fmt.Print(schema)
	return nil
}
