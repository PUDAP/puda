package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	"github.com/spf13/cobra"
)

var machineHomeCmd = &cobra.Command{
	Use:   "home <machine_id> [machine_id...]",
	Short: "Send home commands to one or more machines",
	Args:  cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return homeMachines(args)
	},
}

func init() {
	machineCmd.AddCommand(machineHomeCmd)
}

func homeMachines(machineIDs []string) error {
	globalConfig, err := puda.LoadGlobalConfig()
	if err != nil {
		return fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
	}
	userID := globalConfig.User.UserID
	username := globalConfig.User.Username
	if userID == "" || username == "" {
		return fmt.Errorf("user not logged in. Please run 'puda login' first")
	}

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

	runID := uuid.New().String()
	if store != nil {
		if err := store.InsertRun(runID, nil); err != nil {
			return fmt.Errorf("failed to create run for home command: %w", err)
		}
	}

	requests := make([]puda.CommandRequest, 0, len(machineIDs))
	for i, machineID := range machineIDs {
		requests = append(requests, puda.CommandRequest{
			Name:       "home",
			Params:     make(map[string]interface{}),
			StepNumber: i + 1,
			Version:    "1.0",
			MachineID:  machineID,
		})
	}

	if err := pudanats.SendQueueCommands(js, dispatcher, requests, runID, userID, username, store); err != nil {
		return fmt.Errorf("home command failed: %w", err)
	}

	fmt.Fprintf(os.Stdout, "Home commands sent successfully to %d machine(s)\n", len(machineIDs))
	return nil
}
