package cli

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/spf13/cobra"
)

var protocolNoteCmd = &cobra.Command{
	Use:   "note",
	Short: "Append a UTC-stamped note to an existing protocol run",
	Long: `Append text to a protocol-associated run in the project database.
Existing notes are preserved. Markdown links to reports, plots, logs and data
are stored verbatim, without reading or uploading the linked files.
Returns JSON containing the run ID and the saved notes.

Example:
  puda protocol note --run <run-id> --text "Result: [plot](plots/result.svg)"`,
	Args: cobra.NoArgs,
	RunE: runProtocolNote,
}

func init() {
	protocolNoteCmd.Flags().String("run", "", "Existing protocol run ID (required)")
	protocolNoteCmd.Flags().String("text", "", "Note text to append (required, nonblank)")
	protocolNoteCmd.MarkFlagRequired("run")
	protocolNoteCmd.MarkFlagRequired("text")
	protocolCmd.AddCommand(protocolNoteCmd)
}

func runProtocolNote(cmd *cobra.Command, args []string) error {
	runID, _ := cmd.Flags().GetString("run")
	text, _ := cmd.Flags().GetString("text")
	if strings.TrimSpace(text) == "" {
		return fmt.Errorf("--text cannot be blank")
	}
	store, err := db.Connect()
	if err != nil {
		return err
	}
	defer store.Disconnect()
	notes, err := store.AppendProtocolNote(runID, text)
	if err != nil {
		return err
	}
	return json.NewEncoder(cmd.OutOrStdout()).Encode(struct {
		RunID string `json:"run_id"`
		Notes string `json:"notes"`
	}{RunID: runID, Notes: notes})
}
