package cli

import (
	"fmt"
	"os"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

const resetTimeoutSeconds = 5

// resetMachine sends the reset immediate command to a machine via NATS
func resetMachine(machineID string) error {
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

	response, err := nats.SendResetCommand(nc, js, machineID, "", userID, username, resetTimeoutSeconds, store)
	if err != nil {
		return err
	}
	if response.Response != nil && response.Response.Status == puda.StatusError {
		msg := "unknown error"
		if response.Response.Message != nil {
			msg = *response.Response.Message
		}
		return fmt.Errorf("reset failed: %s", msg)
	}
	fmt.Fprintf(os.Stdout, "Reset command sent successfully to %s\n", machineID)
	return nil
}
