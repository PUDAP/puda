package nats

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	natsio "github.com/nats-io/nats.go"
)

const (
	kvBucketMachineState    = "MACHINE_STATE"
	kvBucketMachineCommands = "MACHINE_COMMANDS"
	fleetPingSubject        = "puda.cmd.ping"
)

// PingResult is the outcome of a direct Core NATS ping request.
type PingResult struct {
	MachineID     string  `json:"machine_id"`
	Status        string  `json:"status"`
	Timestamp     string  `json:"timestamp,omitempty"`
	SDKVersion    string  `json:"sdk_version,omitempty"`
	UptimeSeconds float64 `json:"uptime_seconds,omitempty"`
	RunStatus     string  `json:"run_status,omitempty"`
	LatencyMS     float64 `json:"latency_ms"`
	Error         string  `json:"error,omitempty"`
}

// WatchEvent represents a single message from a machine (telemetry, event, or command).
type WatchEvent struct {
	Timestamp time.Time       `json:"timestamp"`
	Subject   string          `json:"subject"`
	MachineID string          `json:"machine_id"`
	Category  string          `json:"category"` // "tlm", "evt", or "cmd"
	Topic     string          `json:"topic"`
	Data      json.RawMessage `json:"data"`
}

// WatchOpts configures which subjects SubscribeMachineSubjects subscribes to.
type WatchOpts struct {
	// Subjects limits output to messages whose "category.topic" starts with one
	// of these prefixes (e.g. "tlm.health", "cmd.response"). Nil or empty means
	// all subjects pass.
	Subjects map[string]struct{}
	// IncludeHeartbeat must be true to receive heartbeat messages.
	// Heartbeats are excluded by default because they are high-frequency
	// and already consumed by ListMachines.
	IncludeHeartbeat bool
}

func parsePong(data []byte) (PingResult, bool) {
	var pong PingResult
	if err := json.Unmarshal(data, &pong); err != nil {
		return PingResult{}, false
	}
	if pong.Status != "pong" || pong.MachineID == "" {
		return PingResult{}, false
	}
	return pong, true
}

func machineIDFromPong(data []byte) (string, bool) {
	pong, ok := parsePong(data)
	return pong.MachineID, ok
}

func uniqueMachineIDs(machineIDs []string) []string {
	unique := make([]string, 0, len(machineIDs))
	seen := make(map[string]struct{}, len(machineIDs))
	for _, machineID := range machineIDs {
		if _, exists := seen[machineID]; exists {
			continue
		}
		seen[machineID] = struct{}{}
		unique = append(unique, machineID)
	}
	return unique
}

func machinePingSubject(machineID string) string {
	return fmt.Sprintf("puda.%s.cmd.ping", strings.ReplaceAll(machineID, ".", "-"))
}

func watchEventFromMsg(msg *natsio.Msg) (WatchEvent, bool) {
	parts := strings.Split(msg.Subject, ".")
	if len(parts) < 4 {
		return WatchEvent{}, false
	}

	var data json.RawMessage
	if json.Valid(msg.Data) {
		data = msg.Data
	} else {
		data, _ = json.Marshal(string(msg.Data))
	}

	return WatchEvent{
		Timestamp: time.Now().UTC(),
		Subject:   msg.Subject,
		MachineID: parts[1],
		Category:  parts[2],
		Topic:     strings.Join(parts[3:], "."),
		Data:      data,
	}, true
}

func shouldEmitWatchEvent(evt WatchEvent, opts WatchOpts) bool {
	if !opts.IncludeHeartbeat && evt.Topic == "heartbeat" {
		return false
	}
	if len(opts.Subjects) == 0 {
		return true
	}
	catTopic := evt.Category + "." + evt.Topic
	for filter := range opts.Subjects {
		if catTopic == filter || strings.HasPrefix(catTopic, filter+".") {
			return true
		}
	}
	return false
}

func watchSubjects(machineIDs []string) []string {
	if len(machineIDs) == 0 {
		return []string{"puda.*.>"}
	}
	subjects := make([]string, 0, len(machineIDs))
	for _, id := range machineIDs {
		subjects = append(subjects, fmt.Sprintf("puda.%s.>", id))
	}
	return subjects
}

// PingMachines sends direct Core NATS ping requests concurrently.
func PingMachines(nc *natsio.Conn, machineIDs []string, timeout time.Duration) []PingResult {
	unique := uniqueMachineIDs(machineIDs)
	results := make([]PingResult, len(unique))
	var wg sync.WaitGroup
	for i, machineID := range unique {
		wg.Add(1)
		go func() {
			defer wg.Done()
			started := time.Now()
			msg, err := nc.Request(machinePingSubject(machineID), []byte("ping"), timeout)
			latencyMS := float64(time.Since(started)) / float64(time.Millisecond)
			if err != nil {
				results[i] = PingResult{MachineID: machineID, Status: "error", LatencyMS: latencyMS, Error: err.Error()}
				return
			}
			pong, ok := parsePong(msg.Data)
			if !ok {
				results[i] = PingResult{MachineID: machineID, Status: "error", LatencyMS: latencyMS, Error: "invalid pong response"}
				return
			}
			pong.LatencyMS = latencyMS
			results[i] = pong
		}()
	}
	wg.Wait()
	return results
}

// SubscribeMachineSubjects subscribes to puda.<id>.> for every machine ID in
// the slice, or puda.*.> when machineIDs is empty. It captures machine traffic
// and multiplexes all messages into a single channel.
func SubscribeMachineSubjects(ctx context.Context, nc *natsio.Conn, machineIDs []string, opts WatchOpts) (<-chan WatchEvent, error) {
	ch := make(chan WatchEvent, 64)

	handler := func(msg *natsio.Msg) {
		evt, ok := watchEventFromMsg(msg)
		if !ok || !shouldEmitWatchEvent(evt, opts) {
			return
		}
		select {
		case ch <- evt:
		case <-ctx.Done():
		}
	}

	subjects := watchSubjects(machineIDs)
	subs := make([]*natsio.Subscription, 0, len(subjects))
	for _, subject := range subjects {
		sub, err := nc.Subscribe(subject, handler)
		if err != nil {
			for _, s := range subs {
				s.Unsubscribe()
			}
			close(ch)
			return nil, fmt.Errorf("failed to subscribe to %s: %w", subject, err)
		}
		subs = append(subs, sub)
	}

	go func() {
		<-ctx.Done()
		for _, s := range subs {
			s.Unsubscribe()
		}
		nc.Flush()
		close(ch)
	}()

	return ch, nil
}

// ListMachines broadcasts a Core NATS ping and gathers unique pong replies.
func ListMachines(nc *natsio.Conn, timeout time.Duration) ([]string, error) {
	seen := make(map[string]struct{})
	inbox := natsio.NewInbox()
	sub, err := nc.SubscribeSync(inbox)
	if err != nil {
		return nil, fmt.Errorf("failed to subscribe to ping replies: %w", err)
	}
	defer sub.Unsubscribe()
	if err := sub.SetPendingLimits(1_000_000, 256*1024*1024); err != nil {
		return nil, fmt.Errorf("failed to set ping reply buffer limits: %w", err)
	}
	if err := nc.Flush(); err != nil {
		return nil, fmt.Errorf("failed to activate ping reply inbox: %w", err)
	}
	if err := nc.PublishRequest(fleetPingSubject, inbox, []byte("ping")); err != nil {
		return nil, fmt.Errorf("failed to publish fleet ping: %w", err)
	}
	if err := nc.Flush(); err != nil {
		return nil, fmt.Errorf("failed to flush fleet ping: %w", err)
	}

	deadline := time.Now().Add(timeout)
	for {
		remaining := time.Until(deadline)
		if remaining <= 0 {
			break
		}
		msg, err := sub.NextMsg(remaining)
		if errors.Is(err, natsio.ErrTimeout) || errors.Is(err, natsio.ErrNoResponders) {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("failed while collecting ping replies: %w", err)
		}
		if machineID, ok := machineIDFromPong(msg.Data); ok {
			seen[machineID] = struct{}{}
		}
	}

	machines := make([]string, 0, len(seen))
	for id := range seen {
		machines = append(machines, id)
	}
	return machines, nil
}

// ListMachineStateMachines returns machine IDs that have a key in MACHINE_STATE.
func ListMachineStateMachines(nc *natsio.Conn) ([]string, error) {
	js, err := nc.JetStream()
	if err != nil {
		return nil, fmt.Errorf("failed to get JetStream context: %w", err)
	}

	kv, err := js.KeyValue(kvBucketMachineState)
	if err != nil {
		// Bucket not created yet — no persisted state.
		return []string{}, nil
	}

	keys, err := kv.Keys()
	if err != nil {
		if errors.Is(err, natsio.ErrNoKeysFound) {
			return []string{}, nil
		}
		return nil, fmt.Errorf("failed to list MACHINE_STATE keys: %w", err)
	}
	return keys, nil
}

// GetMachineCommands retrieves the commands of a specific machine from KV store
func GetMachineCommands(nc *natsio.Conn, machineID string) error {
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}
	kv, err := js.KeyValue(kvBucketMachineCommands)
	if err != nil {
		return fmt.Errorf("failed to get KV bucket: %w", err)
	}

	entry, err := kv.Get(machineID)
	if err != nil {
		return fmt.Errorf("failed to get %s commands: %w", machineID, err)
	}

	var commands map[string]string
	if err := json.Unmarshal(entry.Value(), &commands); err != nil {
		return fmt.Errorf("failed to parse commands JSON: %w", err)
	}

	fmt.Println(commands["commands"])

	return nil
}

// GetMachineState retrieves the state of a specific machine from KV store.
func GetMachineState(nc *natsio.Conn, machineID string) (json.RawMessage, error) {
	js, err := nc.JetStream()
	if err != nil {
		return nil, fmt.Errorf("failed to get JetStream context: %w", err)
	}

	kv, err := js.KeyValue(kvBucketMachineState)
	if err != nil {
		return nil, fmt.Errorf("KV bucket not found: %w", err)
	}

	entry, err := kv.Get(machineID)
	if err != nil {
		return nil, fmt.Errorf("failed to get machine state: %w", err)
	}

	state := append(json.RawMessage(nil), entry.Value()...)
	if !json.Valid(state) {
		return nil, fmt.Errorf("failed to parse state JSON")
	}

	return state, nil
}

// GetSingleMachineState retrieves and prints the state of a specific machine from KV store.
func GetSingleMachineState(nc *natsio.Conn, machineID string) error {
	state, err := GetMachineState(nc, machineID)
	if err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("Could not get state for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return err
	}

	var prettyState interface{}
	if err := json.Unmarshal(state, &prettyState); err != nil {
		return fmt.Errorf("failed to parse state JSON: %w", err)
	}

	jsonBytes, err := json.MarshalIndent(prettyState, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}
	fmt.Println(string(jsonBytes))

	return nil
}
