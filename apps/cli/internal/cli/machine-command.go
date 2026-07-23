package cli

import (
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	pudanats "github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

const immediateCommandTimeoutSeconds = 5

var machineStartRunID string
var machineCompleteRunID string

var machinePauseCmd = &cobra.Command{
	Use:   "pause <machine_ids>",
	Short: "Pause one or more machines",
	Long: `Send pause immediate command to one or more machines.
Machine IDs can be comma-separated, e.g. puda machine pause biologic,first`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return runImmediateCommandForMachines(parseMachineIDs(args), "Pause", "", pudanats.SendPauseCommand)
	},
}

var machineResumeCmd = &cobra.Command{
	Use:   "resume <machine_ids>",
	Short: "Resume one or more machines",
	Long: `Send resume immediate command to one or more machines.
Machine IDs can be comma-separated, e.g. puda machine resume biologic,first`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return runImmediateCommandForMachines(parseMachineIDs(args), "Resume", "", pudanats.SendResumeCommand)
	},
}

var machineResetCmd = &cobra.Command{
	Use:   "reset <machine_ids>",
	Short: "Reset one or more machines",
	Long: `Send reset immediate command to one or more machines.
Machine IDs can be comma-separated, e.g. puda machine reset biologic,first`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		return runImmediateCommandForMachines(parseMachineIDs(args), "Reset", "", pudanats.SendResetCommand)
	},
}

var machineStartCmd = &cobra.Command{
	Use:   "start <machine_ids>",
	Short: "Start a run on one or more machines",
	Long: `Send start immediate command to one or more machines.
Machine IDs can be comma-separated, e.g. puda machine start biologic,first

Use --run-id to set the run ID. If omitted, a random UUIDv4 is generated.`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		runID := resolveRunID(machineStartRunID)
		fmt.Printf("Run ID: %s\n", runID)
		return runImmediateCommandForMachines(parseMachineIDs(args), "Start", runID, pudanats.SendStartCommand)
	},
}

var machineCompleteCmd = &cobra.Command{
	Use:   "complete <machine_ids>",
	Short: "Complete a run on one or more machines",
	Long: `Send complete immediate command to one or more machines.
Machine IDs can be comma-separated, e.g. puda machine complete biologic,first

Use --run-id to set the run ID. If omitted, a random UUIDv4 is generated.`,
	Args: cobra.MinimumNArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		runID := resolveRunID(machineCompleteRunID)
		fmt.Printf("Run ID: %s\n", runID)
		return runImmediateCommandForMachines(parseMachineIDs(args), "Complete", runID, sendCompleteCommand)
	},
}

func init() {
	machineStartCmd.Flags().StringVar(&machineStartRunID, "run-id", "", "Run ID (default: random UUIDv4)")
	machineCompleteCmd.Flags().StringVar(&machineCompleteRunID, "run-id", "", "Run ID (default: random UUIDv4)")
	machineCmd.AddCommand(machinePauseCmd)
	machineCmd.AddCommand(machineResumeCmd)
	machineCmd.AddCommand(machineResetCmd)
	machineCmd.AddCommand(machineStartCmd)
	machineCmd.AddCommand(machineCompleteCmd)
}

func resolveRunID(runID string) string {
	if runID != "" {
		return runID
	}
	return uuid.New().String()
}

func sendCompleteCommand(
	js nats.JetStreamContext,
	dispatcher *pudanats.ResponseDispatcher,
	machineID, runID, userID, username string,
	timeoutSeconds int,
	store *db.Store,
) (*puda.NATSMessage, error) {
	return pudanats.SendCompleteCommand(js, dispatcher, machineID, runID, userID, username, timeoutSeconds, 0, store)
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

func runImmediateCommandForMachines(
	machineIDs []string,
	commandLabel string,
	runID string,
	send immediateCommandSender,
) error {
	if len(machineIDs) == 0 {
		return fmt.Errorf("at least one machine ID is required")
	}

	nc, err := connectMachineNATS()
	if err != nil {
		return err
	}
	defer nc.Close()

	onlineMachines, err := pudanats.ListMachines(nc, heartbeatTimeout)
	if err != nil {
		return fmt.Errorf("failed to list online machines: %w", err)
	}

	onlineMachineSet := machineIDSet(onlineMachines)
	onlineMachineIDs, offlineMachineIDs := splitImmediateCommandTargets(machineIDs, onlineMachineSet)
	if len(onlineMachineIDs) == 0 {
		for _, machineID := range machineIDs {
			writeImmediateCommandResult(os.Stdout, commandLabel, machineID, fmt.Errorf("offline or does not exist"))
		}
		return fmt.Errorf("%s command failed for %d machine(s)", strings.ToLower(commandLabel), len(machineIDs))
	}

	pendingOnlineMachineIDs := make([]string, 0, len(onlineMachineIDs))
	for _, machineID := range machineIDs {
		if _, found := onlineMachineSet[machineID]; found {
			pendingOnlineMachineIDs = append(pendingOnlineMachineIDs, machineID)
			continue
		}
		if err := flushImmediateCommandTargets(pendingOnlineMachineIDs, commandLabel, runID, send); err != nil {
			return err
		}
		pendingOnlineMachineIDs = pendingOnlineMachineIDs[:0]
		writeImmediateCommandResult(os.Stdout, commandLabel, machineID, fmt.Errorf("offline or does not exist"))
	}
	if err := flushImmediateCommandTargets(pendingOnlineMachineIDs, commandLabel, runID, send); err != nil {
		return err
	}

	if len(offlineMachineIDs) > 0 {
		return fmt.Errorf("%s command failed for %d machine(s)", strings.ToLower(commandLabel), len(offlineMachineIDs))
	}
	return nil
}

func flushImmediateCommandTargets(
	machineIDs []string,
	commandLabel string,
	runID string,
	send immediateCommandSender,
) error {
	if len(machineIDs) == 0 {
		return nil
	}
	return sendImmediateCommandToMachines(machineIDs, commandLabel, runID, send)
}

func sendImmediateCommandToMachines(
	machineIDs []string,
	commandLabel string,
	runID string,
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

	failedCount := 0
	for _, machineID := range machineIDs {
		response, err := send(js, dispatcher, machineID, runID, userID, username, immediateCommandTimeoutSeconds, store)
		if err != nil {
			failedCount++
			writeImmediateCommandResult(os.Stdout, commandLabel, machineID, err)
			continue
		}
		if response.Response != nil && response.Response.Status == puda.StatusError {
			msg := "unknown error"
			if response.Response.Message != nil {
				msg = *response.Response.Message
			}
			failedCount++
			writeImmediateCommandResult(os.Stdout, commandLabel, machineID, fmt.Errorf("%s", msg))
			continue
		}
		writeImmediateCommandResult(os.Stdout, commandLabel, machineID, nil)
	}

	if failedCount > 0 {
		return fmt.Errorf("%s command failed for %d machine(s)", strings.ToLower(commandLabel), failedCount)
	}
	return nil
}

func splitImmediateCommandTargets(machineIDs []string, onlineMachines map[string]struct{}) ([]string, []string) {
	online := make([]string, 0, len(machineIDs))
	offline := make([]string, 0)
	for _, machineID := range machineIDs {
		if _, found := onlineMachines[machineID]; found {
			online = append(online, machineID)
			continue
		}
		offline = append(offline, machineID)
	}
	return online, offline
}

func writeImmediateCommandResult(w io.Writer, commandLabel, machineID string, err error) {
	commandName := strings.ToLower(commandLabel)
	if err != nil {
		fmt.Fprintf(w, "%s: %s command failed: %v\n", machineID, commandName, err)
		return
	}
	fmt.Fprintf(w, "%s: %s command sent successfully\n", machineID, commandName)
}
