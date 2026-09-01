package nats

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"os/signal"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/db"
	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
)

func requireSuccessfulLifecycleResponse(commandName string, response *puda.NATSMessage) error {
	if response == nil || response.Response == nil {
		return fmt.Errorf("%s response is missing response data", commandName)
	}
	if response.Response.Status != puda.StatusSuccess {
		if response.Response.Status == puda.StatusError {
			return fmt.Errorf("%s failed: %s", commandName, GetResponseMessage(response))
		}
		return fmt.Errorf("%s response has unexpected status %q", commandName, response.Response.Status)
	}
	return nil
}

func requireSuccessfulQueueResponse(response *puda.NATSMessage) error {
	return requireSuccessfulLifecycleResponse("queued command", response)
}

func completeMachines(machineIDs []string, completeFn func(string) error) error {
	var completeErrs []error
	for _, machineID := range machineIDs {
		if err := completeFn(machineID); err != nil {
			completeErrs = append(completeErrs, fmt.Errorf("COMPLETE command failed for machine %s: %w", machineID, err))
		}
	}
	return errors.Join(completeErrs...)
}

// completeAllMachines sends COMPLETE commands to all started machines and
// returns every failure as one joined error.
func completeAllMachines(js nats.JetStreamContext, dispatcher *ResponseDispatcher, startedMachines []string, runID, userID, username string, timeoutSeconds int, stepNumber int, store *db.Store) error {
	log.Printf("Completing runs on all machines")
	return completeMachines(startedMachines, func(machineID string) error {
		response, err := SendCompleteCommand(js, dispatcher, machineID, runID, userID, username, timeoutSeconds, stepNumber, store)
		if err != nil {
			return err
		}
		return requireSuccessfulLifecycleResponse("COMPLETE", response)
	})
}

type startedMachineCleanup struct {
	mu          sync.Mutex
	once        sync.Once
	machines    map[string]struct{}
	completeFn  func([]string) error
	completeErr error
}

func newStartedMachineCleanup(completeFn func([]string) error) *startedMachineCleanup {
	return &startedMachineCleanup{machines: make(map[string]struct{}), completeFn: completeFn}
}

func (cleanup *startedMachineCleanup) markStarted(machineID string) {
	cleanup.mu.Lock()
	cleanup.machines[machineID] = struct{}{}
	cleanup.mu.Unlock()
}

func (cleanup *startedMachineCleanup) complete() error {
	cleanup.once.Do(func() {
		cleanup.mu.Lock()
		machineIDs := make([]string, 0, len(cleanup.machines))
		for machineID := range cleanup.machines {
			machineIDs = append(machineIDs, machineID)
		}
		cleanup.mu.Unlock()
		sort.Strings(machineIDs)
		cleanup.completeErr = cleanup.completeFn(machineIDs)
	})
	return cleanup.completeErr
}

func joinProtocolAndCleanupErrors(protocolErr, cleanupErr error) error {
	return errors.Join(protocolErr, cleanupErr)
}

type commandResult struct {
	index    int
	request  puda.CommandRequest
	response *puda.NATSMessage
	err      error
}

// StepRange selects an inclusive range of protocol steps. EndStep 0 means
// through the final protocol step.
type StepRange struct {
	StartStep int
	EndStep   int
}

// StepConfirmationFunc gates a protocol step before its commands are sent.
// Returning an error aborts the run without dispatching that step.
type StepConfirmationFunc func(ctx context.Context, stepNumber int, commands []puda.CommandRequest) error

func requestStepConfirmation(ctx context.Context, stepNumber int, commands []puda.CommandRequest, confirmation StepConfirmationFunc) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if confirmation == nil {
		return nil
	}
	if err := confirmation(ctx, stepNumber, commands); err != nil {
		return err
	}
	return ctx.Err()
}

func sendQueueCommandBatch(ctx context.Context, publishInterlock *sync.Mutex, js nats.JetStreamContext, dispatcher *ResponseDispatcher, requests []puda.CommandRequest, startIndex int, totalCommands int, runID, userID, username string, store *db.Store) error {
	if len(requests) == 1 {
		request := requests[0]
		log.Printf("Sending command %d/%d: %s (step %d) to machine %s", startIndex+1, totalCommands, request.Name, request.StepNumber, request.MachineID)
	} else {
		log.Printf("Sending %d commands in parallel for step %d", len(requests), requests[0].StepNumber)
		for idx, request := range requests {
			log.Printf("Sending command %d/%d: %s (step %d) to machine %s", startIndex+idx+1, totalCommands, request.Name, request.StepNumber, request.MachineID)
		}
	}

	results := make(chan commandResult, len(requests))
	var wg sync.WaitGroup
	for idx, request := range requests {
		wg.Add(1)
		go func(idx int, request puda.CommandRequest) {
			defer wg.Done()
			response, err := SendQueueCommandWithContext(ctx, publishInterlock, js, dispatcher, request, runID, userID, username, store)
			results <- commandResult{
				index:    startIndex + idx,
				request:  request,
				response: response,
				err:      err,
			}
		}(idx, request)
	}

	wg.Wait()
	close(results)

	for result := range results {
		commandPosition := result.index + 1
		if result.err != nil {
			return fmt.Errorf("command %d/%d failed or timed out: %w", commandPosition, totalCommands, result.err)
		}

		if err := requireSuccessfulQueueResponse(result.response); err != nil {
			return fmt.Errorf("command %d/%d failed: %w", commandPosition, totalCommands, err)
		}

		log.Printf("Command %d/%d succeeded: %s (step %d)", commandPosition, totalCommands, result.request.Name, result.request.StepNumber)

		// Log response details
		responseJSON, err := json.MarshalIndent(result.response, "", "  ")
		if err != nil {
			log.Printf("Response (unable to marshal): %+v", result.response)
		} else {
			log.Printf("Response: %s", string(responseJSON))
		}
	}

	return nil
}

// SendQueueCommands sends queued protocol commands. Pass nil confirmation to
// dispatch every step without an interactive gate.
func SendQueueCommands(js nats.JetStreamContext, dispatcher *ResponseDispatcher, requests []puda.CommandRequest, runID, userID, username string, store *db.Store, confirmation StepConfirmationFunc) (returnErr error) {
	const defaultTimeout = 30 // for immediate commands which should complete pretty much instantly

	if len(requests) == 0 {
		return fmt.Errorf("no commands to send")
	}

	completeStepNumber := len(requests) + 1
	if lastStepNumber := requests[len(requests)-1].StepNumber; lastStepNumber > 0 {
		completeStepNumber = lastStepNumber + 1
	}

	// Collect unique machine IDs
	machineIDs := make(map[string]bool)
	for _, req := range requests {
		if req.MachineID == "" {
			return fmt.Errorf("command missing machine_id: %+v", req)
		}
		machineIDs[req.MachineID] = true
	}

	machineIDList := make([]string, 0, len(machineIDs))
	for id := range machineIDs {
		machineIDList = append(machineIDList, id)
	}

	// Set up signal handling for graceful shutdown. Cancellation takes the same
	// interlock as queue publication, so no publish can begin after cancellation.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var publishInterlock sync.Mutex

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(sigChan)
	signalDone := make(chan struct{})
	defer close(signalDone)

	cleanup := newStartedMachineCleanup(func(machineIDs []string) error {
		return completeAllMachines(js, dispatcher, machineIDs, runID, userID, username, defaultTimeout, completeStepNumber, store)
	})
	defer func() {
		returnErr = joinProtocolAndCleanupErrors(returnErr, cleanup.complete())
	}()

	// Signal handling only requests cancellation. COMPLETE publication is
	// centralized in the main execution path's once-only deferred cleanup.
	go func() {
		select {
		case <-sigChan:
		case <-signalDone:
			return
		}
		fmt.Fprintln(os.Stderr, "Gracefully Stopping... press Ctrl+C again to force")
		log.Printf("Interrupt signal received; stopping command publication...")
		publishInterlock.Lock()
		cancel()
		publishInterlock.Unlock()

		select {
		case <-sigChan:
			fmt.Fprintln(os.Stderr, "Force stopping.")
			os.Exit(1)
		case <-signalDone:
		}
	}()

	// Send START commands to all machines
	log.Printf("Sending START commands to all machines: %v", machineIDList)
	for _, machineID := range machineIDList {
		if ctx.Err() != nil {
			return fmt.Errorf("interrupted before starting machines")
		}

		response, err := SendStartCommandWithContext(ctx, &publishInterlock, js, dispatcher, machineID, runID, userID, username, defaultTimeout, store, func() {
			cleanup.markStarted(machineID)
		})
		if err != nil {
			return fmt.Errorf("START command failed for machine %s: %w", machineID, err)
		}
		if err := requireSuccessfulLifecycleResponse("START", response); err != nil {
			return fmt.Errorf("START command failed for machine %s: %w", machineID, err)
		}
	}

	// Send commands step-by-step. Commands with the same step number form a
	// barrier: they are sent in parallel, then all must finish before moving on.
	for idx := 0; idx < len(requests); {
		if ctx.Err() != nil {
			return fmt.Errorf("interrupted during command execution")
		}

		stepNumber := requests[idx].StepNumber
		batchEnd := idx + 1
		for batchEnd < len(requests) && requests[batchEnd].StepNumber == stepNumber {
			batchEnd++
		}

		if err := requestStepConfirmation(ctx, stepNumber, requests[idx:batchEnd], confirmation); err != nil {
			return fmt.Errorf("step %d confirmation failed: %w", stepNumber, err)
		}

		if err := sendQueueCommandBatch(ctx, &publishInterlock, js, dispatcher, requests[idx:batchEnd], idx, len(requests), runID, userID, username, store); err != nil {
			return err
		}
		idx = batchEnd
	}

	log.Printf("All %d commands completed successfully", len(requests))
	log.Printf("Sending COMPLETE commands to all machines: %v", machineIDList)
	return nil
}

// RunProtocol executes a protocol. confirmation is invoked immediately before
// each selected step is dispatched; nil skips the gate.
// stepRanges selects inclusive step ranges; nil or empty means the full protocol.
func RunProtocol(protocolFile *puda.ProtocolFile, natsServers string, stepRanges []StepRange, confirmation StepConfirmationFunc) error {
	// Initialize database connection (optional - if it fails, database operations will be skipped gracefully)
	store, err := db.Connect()
	if err != nil {
		log.Printf("Warning: failed to connect to database for command logging: %v", err)
		store = nil
	} else {
		defer store.Disconnect()
	}

	// Load global config for NATS servers and user identity
	globalCfg, err := puda.LoadGlobalConfig()
	if err != nil {
		return fmt.Errorf("failed to load global config (run 'puda login' first): %w", err)
	}

	// if natsServers is not provided, use nats_servers from the global config
	finalNatsServers := natsServers
	if finalNatsServers == "" {
		finalNatsServers = globalCfg.NATSServers
	}
	if finalNatsServers == "" {
		return fmt.Errorf("NATS servers not configured; run 'puda config set nats_servers <url>'")
	}

	// Fetch user identity from config
	finalUserID := globalCfg.User.UserID
	finalUsername := globalCfg.User.Username
	if finalUserID == "" || finalUsername == "" {
		return fmt.Errorf("user not logged in. Please run 'puda login' first")
	}

	// Insert run into database
	runID := uuid.New().String()
	if store != nil {
		if err := store.InsertRun(runID, &protocolFile.ProtocolID); err != nil {
			// Log warning but don't fail - database logging is optional
			log.Printf("Warning: failed to insert run into database: %v", err)
		}
	}

	log.Printf("Protocol created by %s (%s) at %s", finalUsername, finalUserID, protocolFile.Timestamp)
	log.Printf("Description: %s", protocolFile.Description)

	log.Printf("Run ID: %s", runID)
	log.Printf("Ran by: %s (%s)", finalUsername, finalUserID)

	// Parse NATS servers
	log.Printf("Connecting to NATS servers: %v", finalNatsServers)

	// Connect to NATS
	nc, err := nats.Connect(finalNatsServers, nats.MaxReconnects(3), nats.ReconnectWait(2*time.Second))
	if err != nil {
		return fmt.Errorf("failed to connect to NATS: %w", err)
	}
	defer nc.Close()

	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}

	log.Printf("Connected to NATS servers")

	// Create response dispatcher with a single long-lived subscription per user
	dispatcher := NewResponseDispatcher(js, finalUserID)
	if err := dispatcher.Start(); err != nil {
		return fmt.Errorf("failed to start response dispatcher: %w", err)
	}
	defer dispatcher.Close()

	// Extract commands from protocol file
	commands := protocolFile.Commands
	if len(commands) == 0 {
		return fmt.Errorf("protocol contains no commands")
	}

	maxStepNumber := commands[0].StepNumber
	for _, command := range commands[1:] {
		if command.StepNumber > maxStepNumber {
			maxStepNumber = command.StepNumber
		}
	}
	if len(stepRanges) > 0 {
		for _, stepRange := range stepRanges {
			if stepRange.StartStep < 1 || stepRange.StartStep > maxStepNumber {
				return fmt.Errorf("step range start must be between 1 and %d", maxStepNumber)
			}
			endStep := stepRange.EndStep
			if endStep == 0 {
				endStep = maxStepNumber
			}
			if endStep < 1 || endStep > maxStepNumber {
				return fmt.Errorf("step range end must be between 1 and %d", maxStepNumber)
			}
			if endStep < stepRange.StartStep {
				return fmt.Errorf("step range end must be greater than or equal to start")
			}
		}

		log.Printf("Running protocol step selection: %s", formatStepRanges(stepRanges))
		filteredCommands := make([]puda.CommandRequest, 0, len(commands))
		for _, command := range commands {
			if stepSelected(command.StepNumber, stepRanges, maxStepNumber) {
				filteredCommands = append(filteredCommands, command)
			}
		}
		commands = filteredCommands
	}
	log.Printf("Loaded %d commands from protocol, executing %d command(s)\n", len(protocolFile.Commands), len(commands))

	// Send protocol commands
	if err := SendQueueCommands(js, dispatcher, commands, runID, finalUserID, finalUsername, store, confirmation); err != nil {
		log.Printf("Protocol commands failed: %v", err)
		return err
	}

	log.Printf("Protocol commands completed successfully!")
	return nil
}

func stepSelected(stepNumber int, stepRanges []StepRange, maxStepNumber int) bool {
	for _, stepRange := range stepRanges {
		endStep := stepRange.EndStep
		if endStep == 0 {
			endStep = maxStepNumber
		}
		if stepNumber >= stepRange.StartStep && stepNumber <= endStep {
			return true
		}
	}
	return false
}

func formatStepRanges(stepRanges []StepRange) string {
	parts := make([]string, 0, len(stepRanges))
	for _, stepRange := range stepRanges {
		if stepRange.EndStep == 0 {
			parts = append(parts, fmt.Sprintf("%d-", stepRange.StartStep))
		} else if stepRange.StartStep == stepRange.EndStep {
			parts = append(parts, fmt.Sprintf("%d", stepRange.StartStep))
		} else {
			parts = append(parts, fmt.Sprintf("%d-%d", stepRange.StartStep, stepRange.EndStep))
		}
	}
	return strings.Join(parts, ",")
}
