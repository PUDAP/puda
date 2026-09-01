package cli

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/nats"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	natsio "github.com/nats-io/nats.go"
	"github.com/spf13/cobra"
)

// protocolRunCmd is a subcommand of protocolCmd that runs a protocol on machines via NATS
//
// Usage: puda protocol run --file <path>
var protocolRunCmd = &cobra.Command{
	Use:   "run",
	Short: "Run a protocol on machines via NATS",
	Long: `Run a protocol on machines via NATS.
Loads a protocol JSON file from the given path and runs commands step-by-step, stopping on first error.
Commands with the same step_number are sent in parallel and must all finish before the next step runs.
Before a step containing a command with safety.confirm=true, the complete
command and safety context are displayed and execution blocks until "yes" is entered.

Optional: --nats-servers to override NATS server URLs in config file.

Example:
  puda protocol run --file protocol.json --steps 2-5
  puda protocol run --file protocol.json --steps 2-
  puda protocol run --file protocol.json --steps 4,6-7,10-`,
	RunE: runProtocol,
}

// Protocol run flags
var (
	protocolFilePath string
	natsServers      string
	protocolSteps    string
)

// init registers flags for the run command
func init() {
	protocolRunCmd.Flags().StringVarP(&protocolFilePath, "file", "f", "", "Path to JSON file containing protocol (required)")
	protocolRunCmd.Flags().StringVar(&natsServers, "nats-servers", "", "Optional: Comma-separated NATS server URLs - overrides active env")
	protocolRunCmd.Flags().StringVar(&protocolSteps, "steps", "", "Optional: comma-separated steps or inclusive ranges to run (e.g. 3, 2-5, 2-, 4,6-7,10-)")
	protocolRunCmd.MarkFlagRequired("file")
}

// runProtocol executes the run command
func runProtocol(cmd *cobra.Command, args []string) error {
	// Load and parse protocol file
	protocolJSON, err := puda.LoadProtocol(protocolFilePath)
	if err != nil {
		return fmt.Errorf("failed to load protocol file: %w", err)
	}

	var protocolFile puda.ProtocolFile
	if err := json.Unmarshal(protocolJSON, &protocolFile); err != nil {
		return fmt.Errorf("failed to parse protocol JSON: %w", err)
	}

	// Validate protocol
	_, err = puda.ValidateProtocol(&protocolFile)
	if err != nil {
		return err // Error already formatted by ValidateProtocol
	}

	// Resolve safety from the live catalog immediately before execution. The
	// protocol copy is editable planning context and is never authoritative.
	nc, err := connectProtocolRunNATS(natsServers)
	if err != nil {
		return fmt.Errorf("failed to resolve live command safety: %w", err)
	}
	resolvedProtocol, validationErrors := authoritativeProtocolForRun(&protocolFile, func(machineID string) (nats.MachineCommands, error) {
		return nats.GetMachineCommands(nc, machineID)
	})
	nc.Close()
	if len(validationErrors) > 0 {
		return formatProtocolValidationErrors(validationErrors)
	}
	protocolFile = *resolvedProtocol

	// Insert protocol into database
	store, err := db.Connect()
	if err != nil {
		return err
	}
	defer store.Disconnect()

	err = store.InsertProtocol(protocolFile)
	if err != nil {
		return fmt.Errorf("failed to insert protocol into database: %w", err)
	}

	stepRanges, err := protocolStepRanges(cmd)
	if err != nil {
		return err
	}

	confirmationReader := bufio.NewReader(cmd.InOrStdin())
	confirmation := func(ctx context.Context, stepNumber int, commands []puda.CommandRequest) error {
		return confirmProtocolStep(ctx, confirmationReader, cmd.ErrOrStderr(), stepNumber, commands)
	}
	if err := nats.RunProtocol(&protocolFile, natsServers, stepRanges, confirmation); err != nil {
		return fmt.Errorf("failed to run protocol: %w", err)
	}
	return nil
}

func authoritativeProtocolForRun(protocol *puda.ProtocolFile, fetchCatalog func(string) (nats.MachineCommands, error)) (*puda.ProtocolFile, []puda.ValidationError) {
	validated, validationErrors := validateAndEnrichProtocol(protocol, fetchCatalog)
	if len(validationErrors) > 0 {
		return nil, validationErrors
	}

	resolved := *protocol
	resolved.Commands = append([]puda.CommandRequest(nil), protocol.Commands...)
	for index := range resolved.Commands {
		resolved.Commands[index].Safety = validated.Commands[index].Safety
	}
	return &resolved, nil
}

func connectProtocolRunNATS(servers string) (*natsio.Conn, error) {
	if servers == "" {
		cfg, err := puda.LoadGlobalConfig()
		if err != nil {
			return nil, fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
		}
		servers = cfg.NATSServers
	}
	if servers == "" {
		return nil, fmt.Errorf("NATS servers not configured; run 'puda config set nats_servers <url>'")
	}
	nc, err := natsio.Connect(servers, natsio.MaxReconnects(3), natsio.ReconnectWait(2*time.Second))
	if err != nil {
		return nil, fmt.Errorf("failed to connect to NATS: %w", err)
	}
	return nc, nil
}

func confirmProtocolStep(ctx context.Context, input *bufio.Reader, output io.Writer, stepNumber int, commands []puda.CommandRequest) error {
	requiringConfirmation := make([]puda.CommandRequest, 0)
	for _, command := range commands {
		if command.Safety != nil && command.Safety.Confirm {
			requiringConfirmation = append(requiringConfirmation, command)
		}
	}
	if len(requiringConfirmation) == 0 {
		return nil
	}

	fmt.Fprintf(output, "Safety confirmation required for step %d:\n", stepNumber)
	for _, command := range requiringConfirmation {
		commandJSON, err := json.MarshalIndent(command, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to display safety confirmation for step %d: %w", stepNumber, err)
		}
		fmt.Fprintln(output, string(commandJSON))
	}
	fmt.Fprintf(output, "Type yes to continue step %d: ", stepNumber)

	type readResult struct {
		line string
		err  error
	}
	resultChannel := make(chan readResult, 1)
	go func() {
		line, err := input.ReadString('\n')
		resultChannel <- readResult{line: line, err: err}
	}()

	var result readResult
	select {
	case <-ctx.Done():
		return ctx.Err()
	case result = <-resultChannel:
	}
	if result.err != nil && !(result.err == io.EOF && strings.TrimSpace(result.line) != "") {
		if result.err == io.EOF {
			return fmt.Errorf("step %d was not confirmed: confirmation input closed", stepNumber)
		}
		return fmt.Errorf("failed to read safety confirmation for step %d: %w", stepNumber, result.err)
	}
	if !strings.EqualFold(strings.TrimSpace(result.line), "yes") {
		return fmt.Errorf("step %d was not confirmed", stepNumber)
	}
	return nil
}

func protocolStepRanges(cmd *cobra.Command) ([]nats.StepRange, error) {
	if !cmd.Flags().Changed("steps") {
		return nil, nil
	}
	return parseProtocolSteps(protocolSteps)
}

func parseProtocolSteps(value string) ([]nats.StepRange, error) {
	steps := strings.TrimSpace(value)
	if steps == "" {
		return nil, fmt.Errorf("--steps cannot be empty")
	}

	selectors := strings.Split(steps, ",")
	stepRanges := make([]nats.StepRange, 0, len(selectors))
	for _, selector := range selectors {
		stepRange, err := parseProtocolStepRange(selector)
		if err != nil {
			return nil, err
		}
		stepRanges = append(stepRanges, stepRange)
	}
	return stepRanges, nil
}

func parseProtocolStepRange(value string) (nats.StepRange, error) {
	steps := strings.TrimSpace(value)
	if steps == "" {
		return nats.StepRange{}, fmt.Errorf("--steps contains an empty selector")
	}

	if !strings.Contains(steps, "-") {
		step, err := parsePositiveStep(steps)
		if err != nil {
			return nats.StepRange{}, fmt.Errorf("invalid --steps value %q: %w", value, err)
		}
		return nats.StepRange{StartStep: step, EndStep: step}, nil
	}

	if strings.Count(steps, "-") != 1 {
		return nats.StepRange{}, fmt.Errorf("invalid --steps value %q: expected STEP, START-END, or START-", value)
	}

	parts := strings.SplitN(steps, "-", 2)
	if parts[0] == "" && parts[1] == "" {
		return nats.StepRange{}, fmt.Errorf("invalid --steps value %q: expected STEP, START-END, or START-", value)
	}

	start := 1
	if parts[0] != "" {
		parsedStart, err := parsePositiveStep(parts[0])
		if err != nil {
			return nats.StepRange{}, fmt.Errorf("invalid --steps start %q: %w", parts[0], err)
		}
		start = parsedStart
	}

	end := 0
	if parts[1] != "" {
		parsedEnd, err := parsePositiveStep(parts[1])
		if err != nil {
			return nats.StepRange{}, fmt.Errorf("invalid --steps end %q: %w", parts[1], err)
		}
		end = parsedEnd
	}

	if end != 0 && end < start {
		return nats.StepRange{}, fmt.Errorf("--steps end must be greater than or equal to start")
	}
	return nats.StepRange{StartStep: start, EndStep: end}, nil
}

func parsePositiveStep(value string) (int, error) {
	step, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 0, err
	}
	if step < 1 {
		return 0, fmt.Errorf("step must be greater than 0")
	}
	return step, nil
}
