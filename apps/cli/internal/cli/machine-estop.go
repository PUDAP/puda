package cli

import (
	"fmt"
	"io"
	"sync"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/spf13/cobra"
)

var machineEstopCmd = &cobra.Command{
	Use:   "estop <machine_ids>",
	Short: "Emergency stop machine(s) immediately",
	Long: `Send the estop immediate command to machine(s) and report results as JSON.
Machine IDs can be comma-separated, e.g. puda machine estop biologic,first

Use this when a machine must stop now. It never asks for confirmation and does
not ping first: estop is sent to every machine in parallel. On each edge it:
  - runs the driver's estop command on its own thread, even while a queued
    command is executing (the driver stops the hardware);
  - cancels the running queued command and ends the active run;
  - latches the machine in state "estopped": queued commands, start and resume
    are rejected until "puda machine reset <machine_id>" succeeds.

A result is "ok" only when the driver estop returned successfully. Errors mean
the hardware stop may not have happened; check the machine physically:
  - ESTOP_NOT_SUPPORTED: the driver has no estop command; the queue is halted
    but no hardware stop was sent.
  - Unknown immediate command: the edge SDK predates estop (needs SDK 0.0.23+).
  - timeout: no response; the edge may be offline. The estop stays queued and
    runs when that edge reconnects.
Use --human for a text summary.`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return runEstopForMachines(cmd.OutOrStdout(), parseMachineIDs(args), pudanats.SendEstopCommand)
	},
}

func init() {
	machineCmd.AddCommand(machineEstopCmd)
}

// runEstopForMachines sends estop to all machines concurrently, without a ping,
// and reports one result per machine in argument order.
func runEstopForMachines(w io.Writer, machineIDs []string, send immediateCommandSender) error {
	if len(machineIDs) == 0 {
		return fmt.Errorf("at least one machine ID is required")
	}
	globalConfig, err := puda.LoadGlobalConfig()
	if err != nil {
		return fmt.Errorf("failed to load global config: %w", err)
	}
	userID := globalConfig.User.UserID
	username := globalConfig.User.Username

	nc, err := connectMachineNATS()
	if err != nil {
		return err
	}
	defer nc.Close()

	store, err := db.Connect()
	if err != nil {
		store = nil
	} else {
		defer store.Disconnect()
	}

	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}
	dispatcher := pudanats.NewResponseDispatcher(js, userID)
	if err := dispatcher.Start(); err != nil {
		return fmt.Errorf("failed to start response dispatcher: %w", err)
	}
	defer dispatcher.Close()

	results := make([]machineCommandResult, len(machineIDs))
	var wg sync.WaitGroup
	for i, machineID := range machineIDs {
		wg.Add(1)
		go func(i int, machineID string) {
			defer wg.Done()
			response, err := send(js, dispatcher, machineID, "", userID, username, immediateCommandTimeoutSeconds, store)
			if err == nil {
				err = immediateCommandResponseError(response)
			}
			results[i] = machineCommandResultFromError(machineID, err)
		}(i, machineID)
	}
	wg.Wait()

	if err := writeMachineCommandResults(w, "estop", "", "sent", results, machineHuman); err != nil {
		return err
	}
	failed := 0
	for _, result := range results {
		if result.Status != "ok" {
			failed++
		}
	}
	if failed > 0 {
		return immediateCommandFailure("estop", failed)
	}
	return nil
}
