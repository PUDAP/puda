package cli

import (
	"fmt"
	"os"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

const immediateCommandTimeoutSeconds = 5

var machinePauseCmd = &cobra.Command{
	Use:   "pause <machine_ids>",
	Short: "Pause one or more machines",
	Long: `Send pause immediate command to one or more machines.
Machine IDs can be comma-separated, e.g. puda machine pause biologic,first`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return sendImmediateCommandToMachines(parseMachineIDs(args), "Pause", pudanats.SendPauseCommand)
	},
}

var machineResumeCmd = &cobra.Command{
	Use:   "resume <machine_ids>",
	Short: "Resume one or more machines",
	Long: `Send resume immediate command to one or more machines.
Machine IDs can be comma-separated, e.g. puda machine resume biologic,first`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return sendImmediateCommandToMachines(parseMachineIDs(args), "Resume", pudanats.SendResumeCommand)
	},
}

func init() {
	machineCmd.AddCommand(machinePauseCmd)
	machineCmd.AddCommand(machineResumeCmd)
}

func parseMachineIDs(args []string) []string {
	ids := make([]string, 0, len(args))
	for _, arg := range args {
		for _, part := range strings.Split(arg, ",") {
			part = strings.TrimSpace(part)
			if part != "" {
				ids = append(ids, part)
			}
		}
	}
	return ids
}

type immediateCommandSender func(
	js nats.JetStreamContext,
	dispatcher *pudanats.ResponseDispatcher,
	machineID, runID, userID, username string,
	timeoutSeconds int,
	store *db.Store,
) (*puda.NATSMessage, error)

func sendImmediateCommandToMachines(
	machineIDs []string,
	commandLabel string,
	send immediateCommandSender,
) error {
	if len(machineIDs) == 0 {
		return fmt.Errorf("at least one machine ID is required")
	}

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

	for _, machineID := range machineIDs {
		response, err := send(js, dispatcher, machineID, "", userID, username, immediateCommandTimeoutSeconds, store)
		if err != nil {
			return fmt.Errorf("%s command failed for %s: %w", strings.ToLower(commandLabel), machineID, err)
		}
		if response.Response != nil && response.Response.Status == puda.StatusError {
			msg := "unknown error"
			if response.Response.Message != nil {
				msg = *response.Response.Message
			}
			return fmt.Errorf("%s command failed for %s: %s", strings.ToLower(commandLabel), machineID, msg)
		}
	}

	fmt.Fprintf(os.Stdout, "%s command sent successfully to %d machine(s)\n", commandLabel, len(machineIDs))
	return nil
}
