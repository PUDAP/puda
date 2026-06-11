package cli

import (
	"encoding/json"
	"os"
	"sort"
	"time"

	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

type machineStateSnapshot struct {
	Machines  map[string]machineStateResult `json:"machines"`
	Count     int                           `json:"count"`
	FetchedAt time.Time                     `json:"fetched_at"`
}

type machineStateResult struct {
	OK    bool            `json:"ok"`
	State json.RawMessage `json:"state,omitempty"`
	Error string          `json:"error,omitempty"`
}

var machineStateCmd = &cobra.Command{
	Use:   "state [machine_id...]",
	Short: "Get machine state as JSON",
	Long: `Get machine state as a single JSON snapshot and exit.

If no machine IDs are provided, all machines discovered by heartbeat are shown.
Machine IDs can be comma-separated, e.g. puda machine state biologic,first`,
	Args: cobra.ArbitraryArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		machineIDs := parseMachineIDs(args)
		if len(machineIDs) == 0 {
			machineIDs, err = pudanats.ListMachines(nc, heartbeatTimeout)
			if err != nil {
				return err
			}
			sort.Strings(machineIDs)
			if len(machineIDs) == 0 {
				return writeMachineStateSnapshot(nc, machineIDs)
			}
		}

		return writeMachineStateSnapshot(nc, machineIDs)
	},
}

func init() {
	machineCmd.AddCommand(machineStateCmd)
}

func writeMachineStateSnapshot(nc *natsio.Conn, machineIDs []string) error {
	snapshot := machineStateSnapshot{
		Machines:  make(map[string]machineStateResult, len(machineIDs)),
		Count:     len(machineIDs),
		FetchedAt: time.Now().UTC(),
	}

	for _, machineID := range machineIDs {
		state, err := pudanats.GetMachineState(nc, machineID)
		if err != nil {
			snapshot.Machines[machineID] = machineStateResult{
				OK:    false,
				Error: err.Error(),
			}
			continue
		}
		snapshot.Machines[machineID] = machineStateResult{
			OK:    true,
			State: state,
		}
	}

	enc := json.NewEncoder(os.Stdout)
	return enc.Encode(snapshot)
}
