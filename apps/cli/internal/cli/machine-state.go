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
	OK     bool            `json:"ok"`
	Online *bool           `json:"online,omitempty"`
	State  json.RawMessage `json:"state,omitempty"`
	Error  string          `json:"error,omitempty"`
}

var machineStateIncludeOffline bool

var machineStateCmd = &cobra.Command{
	Use:   "state [machine_id...]",
	Short: "Get machine state as JSON",
	Long: `Get machine state as a single JSON snapshot and exit.

If no machine IDs are provided, all machines discovered by heartbeat are shown.
Use --include-offline to also include machines with persisted state that are not
currently sending heartbeats.
Machine IDs can be comma-separated, e.g. puda machine state biologic,first`,
	Args: cobra.ArbitraryArgs,
	RunE: func(cmd *cobra.Command, args []string) error {
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
	machineStateCmd.Flags().BoolVar(&machineStateIncludeOffline, "include-offline", false, "Include machines with persisted state even when no heartbeat is seen")
	machineCmd.AddCommand(machineStateCmd)
}

func resolveMachineStateIDs(nc *natsio.Conn, args []string) ([]string, map[string]struct{}, error) {
	machineIDs := uniqueMachineIDs(parseMachineIDs(args))
	if len(machineIDs) > 0 && !machineStateIncludeOffline {
		sort.Strings(machineIDs)
		return machineIDs, nil, nil
	}

	onlineMachines, err := pudanats.ListMachines(nc, heartbeatTimeout)
	if err != nil {
		return nil, nil, err
	}
	onlineSet := machineIDSet(onlineMachines)

	if len(machineIDs) > 0 {
		sort.Strings(machineIDs)
		return machineIDs, onlineSet, nil
	}

	if machineStateIncludeOffline {
		knownMachines, err := pudanats.ListMachineStateMachines(nc)
		if err != nil {
			return nil, nil, err
		}
		machineIDs = mergeMachineIDs(onlineMachines, knownMachines)
	} else {
		machineIDs = uniqueMachineIDs(onlineMachines)
	}

	sort.Strings(machineIDs)
	return machineIDs, onlineSet, nil
}

func writeMachineStateSnapshot(nc *natsio.Conn, machineIDs []string, onlineMachines map[string]struct{}) error {
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

	enc := json.NewEncoder(os.Stdout)
	return enc.Encode(snapshot)
}

func machineOnlineStatus(machineID string, onlineMachines map[string]struct{}) *bool {
	if onlineMachines == nil {
		return nil
	}
	_, found := onlineMachines[machineID]
	online := found
	return &online
}

func machineIDSet(machineIDs []string) map[string]struct{} {
	set := make(map[string]struct{}, len(machineIDs))
	for _, machineID := range machineIDs {
		set[machineID] = struct{}{}
	}
	return set
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
