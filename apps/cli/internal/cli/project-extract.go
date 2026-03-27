package cli

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/spf13/cobra"
)

var projectExtractID string

// projectExtractCmd extracts all project-linked protocol/run/sample/measurement data.
var projectExtractCmd = &cobra.Command{
	Use:   "extract",
	Short: "Extract project data",
	Long: `Extract project-linked protocol, run, sample, and measurement data.

Example:
  puda project extract --id <project_id>`,
	Args: cobra.NoArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		store, err := db.Connect()
		if err != nil {
			return fmt.Errorf("failed to connect to database: %w", err)
		}
		defer store.Disconnect()

		rows, err := store.QueryProjectExtract(projectExtractID)
		if err != nil {
			return fmt.Errorf("failed to extract project data: %w", err)
		}
		defer rows.Close()

		columns, data, err := scanRows(rows)
		if err != nil {
			return err
		}

		response := map[string]interface{}{
			"status":     "success",
			"project_id": projectExtractID,
			"row_count":  len(data),
			"columns":    columns,
			"data":       data,
		}

		jsonOutput, err := json.MarshalIndent(response, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal JSON: %w", err)
		}

		fmt.Fprintln(os.Stdout, string(jsonOutput))
		return nil
	},
}

func scanRows(rows *sql.Rows) ([]string, []map[string]interface{}, error) {
	columns, err := rows.Columns()
	if err != nil {
		return nil, nil, fmt.Errorf("failed to get columns: %w", err)
	}

	values := make([]interface{}, len(columns))
	valuePtrs := make([]interface{}, len(columns))
	for i := range values {
		valuePtrs[i] = &values[i]
	}

	var data []map[string]interface{}
	for rows.Next() {
		if err := rows.Scan(valuePtrs...); err != nil {
			return nil, nil, fmt.Errorf("failed to scan row: %w", err)
		}

		rowMap := make(map[string]interface{}, len(columns))
		for i, col := range columns {
			val := values[i]
			if val == nil {
				rowMap[col] = nil
				continue
			}

			if b, ok := val.([]byte); ok {
				rowMap[col] = string(b)
				continue
			}

			rowMap[col] = val
		}

		data = append(data, rowMap)
	}

	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("error iterating rows: %w", err)
	}

	return columns, data, nil
}

func init() {
	projectExtractCmd.Flags().StringVar(&projectExtractID, "id", "", "Project ID (required)")
	projectExtractCmd.MarkFlagRequired("id")
}
