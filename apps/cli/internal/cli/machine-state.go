package cli

import (
	"encoding/json"
	"io"
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
	OK     bool            `json:"ok"`
	Online *bool           `json:"online,omitempty"`
	State  json.RawMessage `json:"state,omitempty"`
	Error  string          `json:"error,omitempty"`
}

var machineStateAll bool
var machineStateOffline bool

var machineStateCmd = &cobra.Command{
	Use:   "state [machine_id...]",
	Short: "Get machine state as JSON",
	Long: `Get machine state as a single JSON snapshot and exit.

Provide one or more machine IDs to get specific machine state.
Machine IDs can be comma-separated, e.g. puda machine state first,biologic`,
	Args: cobra.ArbitraryArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
		if len(parseMachineIDs(args)) == 0 && !machineStateAll && !machineStateOffline {
			return cmd.Help()
		}

		nc, err := connectMachineNATS()
		if err != nil {
			return err
		}
		defer nc.Close()

		machineIDs, onlineMachines, err := resolveMachineStateIDs(nc, args)
		if err != nil {
			return err
		}
		return writeMachineStateSnapshot(nc, machineIDs, onlineMachines)
	},
}

func init() {
	machineStateCmd.Flags().BoolVar(&machineStateAll, "all", false, "Show state for all machines discovered by heartbeat")
	machineStateCmd.Flags().BoolVar(&machineStateOffline, "offline", false, "Show machines with persisted state but no heartbeat")
	machineCmd.AddCommand(machineStateCmd)
}

func resolveMachineStateIDs(nc *natsio.Conn, args []string) ([]string, map[string]struct{}, error) {
	machineIDs := uniqueMachineIDs(parseMachineIDs(args))
	if len(machineIDs) > 0 && !machineStateOffline {
		sort.Strings(machineIDs)
		return machineIDs, nil, nil
	}

	onlineMachines, err := pudanats.ListMachines(nc, heartbeatTimeout)
	if err != nil {
		return nil, nil, err
	}
	onlineSet := machineIDSet(onlineMachines)

	if machineStateAll {
		machineIDs = mergeMachineIDs(machineIDs, onlineMachines)
	}

	if machineStateOffline {
		knownMachines, err := pudanats.ListMachineStateMachines(nc)
		if err != nil {
			return nil, nil, err
		}
		machineIDs = mergeMachineIDs(machineIDs, offlineMachineIDs(knownMachines, onlineSet))
	}

	sort.Strings(machineIDs)
	return machineIDs, onlineSet, nil
}

func writeMachineStateSnapshot(nc *natsio.Conn, machineIDs []string, onlineMachines map[string]struct{}) error {
	return writeMachineStateOutput(os.Stdout, nc, machineIDs, onlineMachines)
}

func writeMachineStateOutput(w io.Writer, nc *natsio.Conn, machineIDs []string, onlineMachines map[string]struct{}) error {
	snapshot := machineStateSnapshot{
		Machines:  make(map[string]machineStateResult, len(machineIDs)),
		Count:     len(machineIDs),
		FetchedAt: time.Now().UTC(),
	}

	for _, machineID := range machineIDs {
		online := machineOnlineStatus(machineID, onlineMachines)
		state, err := pudanats.GetMachineState(nc, machineID)
		if err != nil {
			snapshot.Machines[machineID] = machineStateResult{
				OK:     false,
				Online: online,
				Error:  err.Error(),
			}
			continue
		}
		snapshot.Machines[machineID] = machineStateResult{
			OK:     true,
			Online: online,
			State:  state,
		}
	}

	enc := json.NewEncoder(w)
	return enc.Encode(machineStateOutput(snapshot, machineIDs))
}

func machineStateOutput(snapshot machineStateSnapshot, machineIDs []string) any {
	if len(machineIDs) == 1 {
		result := snapshot.Machines[machineIDs[0]]
		if result.OK {
			return result.State
		}
		return result
	}
	return snapshot
}

func machineOnlineStatus(machineID string, onlineMachines map[string]struct{}) *bool {
	if onlineMachines == nil {
		return nil
	}
	_, found := onlineMachines[machineID]
	if !found {
		return nil
	}
	online := true
	return &online
}

func machineIDSet(machineIDs []string) map[string]struct{} {
	set := make(map[string]struct{}, len(machineIDs))
	for _, machineID := range machineIDs {
		set[machineID] = struct{}{}
	}
	return set
}

func offlineMachineIDs(machineIDs []string, onlineMachines map[string]struct{}) []string {
	offline := make([]string, 0, len(machineIDs))
	for _, machineID := range machineIDs {
		if _, online := onlineMachines[machineID]; online {
			continue
		}
		offline = append(offline, machineID)
	}
	return offline
}

func mergeMachineIDs(groups ...[]string) []string {
	merged := make(map[string]struct{})
	for _, group := range groups {
		for _, machineID := range group {
			merged[machineID] = struct{}{}
		}
	}

	machineIDs := make([]string, 0, len(merged))
	for machineID := range merged {
		machineIDs = append(machineIDs, machineID)
	}
	return machineIDs
}

func uniqueMachineIDs(machineIDs []string) []string {
	return mergeMachineIDs(machineIDs)
}
