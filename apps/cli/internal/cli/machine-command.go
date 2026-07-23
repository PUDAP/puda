package cli

import (
	"encoding/json"
	"errors"
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

var errMachineOffline = errors.New("offline or does not exist")

var machineStartRunID string
var machineCompleteRunID string
var machineRunID string
var machineRunParams string
var machineRunKwargs string

var machinePauseCmd = newImmediateMachineCommand(immediateMachineCommandConfig{
	name:   "pause",
	short:  "Pause one or more machines",
	label:  "Pause",
	sender: pudanats.SendPauseCommand,
})

var machineResumeCmd = newImmediateMachineCommand(immediateMachineCommandConfig{
	name:   "resume",
	short:  "Resume one or more machines",
	label:  "Resume",
	sender: pudanats.SendResumeCommand,
})

var machineResetCmd = newImmediateMachineCommand(immediateMachineCommandConfig{
	name:   "reset",
	short:  "Reset one or more machines",
	label:  "Reset",
	sender: pudanats.SendResetCommand,
})

var machineStartCmd = newImmediateMachineCommand(immediateMachineCommandConfig{
	name:      "start",
	short:     "Start a run on one or more machines",
	label:     "Start",
	sender:    pudanats.SendStartCommand,
	runIDFlag: &machineStartRunID,
})

var machineCompleteCmd = newImmediateMachineCommand(immediateMachineCommandConfig{
	name:      "complete",
	short:     "Complete a run on one or more machines",
	label:     "Complete",
	sender:    sendCompleteCommand,
	runIDFlag: &machineCompleteRunID,
})

var machineRunCmd = &cobra.Command{
	Use:   "run <machine_id> <command_name> [params_json]",
	Short: "Run a single machine command",
	Long: `Run one command through the machine queue without sending START or COMPLETE.
Use --run-id to associate the command with an existing run; if it is omitted, a
new UUIDv4 run ID is generated.

Pass command parameters as a JSON object, either as the optional argument or
with --params. Use --kwargs for protocol kwargs when required.

Examples:
  puda machine run first move_electrode '{"deck_slot":"A2","well_name":"A1"}'
  puda machine run biologic CV --params '{"voltage_min":-0.1,"voltage_max":0.1,"cycles":1}' --kwargs '{"channels":[0]}'`,
	Args: cobra.RangeArgs(2, 3),
	RunE: func(cmd *cobra.Command, args []string) error {
		paramsJSON := machineRunParams
		if len(args) == 3 {
			if strings.TrimSpace(paramsJSON) != "" {
				return fmt.Errorf("provide parameters as either [params_json] or --params, not both")
			}
			paramsJSON = args[2]
		}

		params, err := parseMachineRunObject("params", paramsJSON)
		if err != nil {
			return err
		}
		kwargs, err := parseMachineRunObject("kwargs", machineRunKwargs)
		if err != nil {
			return err
		}

		runID := resolveRunID(machineRunID)
		return runSingleMachineCommand(args[0], args[1], params, kwargs, runID)
	},
}

func init() {
	machineStartCmd.Flags().StringVar(&machineStartRunID, "run-id", "", "Run ID (default: random UUIDv4)")
	machineCompleteCmd.Flags().StringVar(&machineCompleteRunID, "run-id", "", "Run ID (default: random UUIDv4)")
	machineRunCmd.Flags().StringVar(&machineRunID, "run-id", "", "Optional run ID (default: random UUIDv4)")
	machineRunCmd.Flags().StringVar(&machineRunParams, "params", "", "Command parameters as a JSON object")
	machineRunCmd.Flags().StringVar(&machineRunKwargs, "kwargs", "", "Command keyword arguments as a JSON object")
	machineCmd.AddCommand(machinePauseCmd)
	machineCmd.AddCommand(machineResumeCmd)
	machineCmd.AddCommand(machineResetCmd)
	machineCmd.AddCommand(machineStartCmd)
	machineCmd.AddCommand(machineCompleteCmd)
	machineCmd.AddCommand(machineRunCmd)
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

func parseMachineRunObject(field, value string) (map[string]interface{}, error) {
	if strings.TrimSpace(value) == "" {
		return make(map[string]interface{}), nil
	}

	var object map[string]interface{}
	if err := json.Unmarshal([]byte(value), &object); err != nil {
		return nil, fmt.Errorf("%s must be a valid JSON object: %w", field, err)
	}
	if object == nil {
		return nil, fmt.Errorf("%s must be a JSON object, not null", field)
	}
	return object, nil
}

func runSingleMachineCommand(machineID, commandName string, params, kwargs map[string]interface{}, runID string) error {
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
		if err := store.InsertRun(runID, nil); err != nil {
			return fmt.Errorf("failed to create run for command: %w", err)
		}
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

	request := puda.CommandRequest{
		Name:       commandName,
		Params:     params,
		Kwargs:     kwargs,
		StepNumber: 1,
		Version:    "1.0",
		MachineID:  machineID,
	}
	response, err := pudanats.SendQueueCommand(js, dispatcher, request, runID, userID, username, store)
	if err != nil {
		return fmt.Errorf("%s command failed: %w", commandName, err)
	}
	if err := queueCommandResponseError(response); err != nil {
		return fmt.Errorf("%s command failed: %w", commandName, err)
	}

	fmt.Fprintf(os.Stdout, "%s: %s command completed successfully\n", machineID, commandName)
	return nil
}

func newImmediateMachineCommand(config immediateMachineCommandConfig) *cobra.Command {
	commandName := strings.ToLower(config.label)
	long := fmt.Sprintf(`Send %s immediate command to one or more machines.
Machine IDs can be comma-separated, e.g. puda machine %s biologic,first`, commandName, config.name)
	if config.runIDFlag != nil {
		long += "\n\nUse --run-id to set the run ID. If omitted, a random UUIDv4 is generated."
	}

	return &cobra.Command{
		Use:   config.name + " <machine_ids>",
		Short: config.short,
		Long:  long,
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			runID := ""
			if config.runIDFlag != nil {
				runID = resolveRunID(*config.runIDFlag)
				fmt.Printf("Run ID: %s\n", runID)
			}
			return runImmediateCommandForMachines(parseMachineIDs(args), config.label, runID, config.sender)
		},
	}
}

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

	listedMachines, err := pudanats.ListMachines(nc, heartbeatTimeout)
	if err != nil {
		return fmt.Errorf("failed to list online machines: %w", err)
	}
	onlineMachines := machineIDSet(listedMachines)

	onlineMachineIDs, offlineMachineIDs := splitImmediateCommandTargets(machineIDs, onlineMachines)
	if len(onlineMachineIDs) == 0 {
		for _, machineID := range machineIDs {
			writeImmediateCommandResult(os.Stdout, commandLabel, machineID, errMachineOffline)
		}
		return immediateCommandFailure(commandLabel, len(machineIDs))
	}

	pendingOnlineMachineIDs := make([]string, 0, len(onlineMachineIDs))
	for _, machineID := range machineIDs {
		if _, found := onlineMachines[machineID]; found {
			pendingOnlineMachineIDs = append(pendingOnlineMachineIDs, machineID)
			continue
		}
		if err := sendImmediateCommandBatch(pendingOnlineMachineIDs, commandLabel, runID, send); err != nil {
			return err
		}
		pendingOnlineMachineIDs = pendingOnlineMachineIDs[:0]
		writeImmediateCommandResult(os.Stdout, commandLabel, machineID, errMachineOffline)
	}
	if err := sendImmediateCommandBatch(pendingOnlineMachineIDs, commandLabel, runID, send); err != nil {
		return err
	}

	if len(offlineMachineIDs) > 0 {
		return immediateCommandFailure(commandLabel, len(offlineMachineIDs))
	}
	return nil
}

func sendImmediateCommandBatch(
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

func immediateCommandFailure(commandLabel string, failedCount int) error {
	return fmt.Errorf("%s command failed for %d machine(s)", strings.ToLower(commandLabel), failedCount)
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
		if err := immediateCommandResponseError(response); err != nil {
			failedCount++
			writeImmediateCommandResult(os.Stdout, commandLabel, machineID, err)
			continue
		}
		writeImmediateCommandResult(os.Stdout, commandLabel, machineID, nil)
	}

	if failedCount > 0 {
		return immediateCommandFailure(commandLabel, failedCount)
	}
	return nil
}

func immediateCommandResponseError(response *puda.NATSMessage) error {
	if response == nil || response.Response == nil || response.Response.Status != puda.StatusError {
		return nil
	}
	if response.Response.Message == nil {
		return errors.New("unknown error")
	}
	return errors.New(*response.Response.Message)
}

func queueCommandResponseError(response *puda.NATSMessage) error {
	if response == nil || response.Response == nil {
		return errors.New("command returned no response data")
	}
	return immediateCommandResponseError(response)
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
