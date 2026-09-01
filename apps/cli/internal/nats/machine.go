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

// MachineCommands is the complete MACHINE_COMMANDS payload. Commands is kept
// for human display; Catalog is the machine-readable validation source.
type MachineCommands struct {
	Commands string           `json:"commands"`
	Catalog  []MachineCommand `json:"catalog"`
}

type MachineCommand struct {
	Name          string                `json:"name"`
	Signature     string                `json:"signature"`
	Doc           *string               `json:"doc"`
	Safety        *MachineCommandSafety `json:"safety"`
	DocPresent    bool                  `json:"-"`
	SafetyPresent bool                  `json:"-"`
}

type MachineCommandSafety struct {
	Summary       string   `json:"summary"`
	Hazards       []string `json:"hazards"`
	Requires      *string  `json:"requires"`
	ForbiddenWhen *string  `json:"forbidden_when"`
	Confirm       *bool    `json:"confirm"`
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

// GetMachineCommands retrieves the human and structured command catalogs.
func GetMachineCommands(nc *natsio.Conn, machineID string) (MachineCommands, error) {
	js, err := nc.JetStream()
	if err != nil {
		return MachineCommands{}, fmt.Errorf("failed to get JetStream context: %w", err)
	}
	kv, err := js.KeyValue(kvBucketMachineCommands)
	if err != nil {
		return MachineCommands{}, fmt.Errorf("failed to get KV bucket: %w", err)
	}

	entry, err := kv.Get(machineID)
	if err != nil {
		return MachineCommands{}, fmt.Errorf("failed to get %s commands: %w", machineID, err)
	}
	return parseMachineCommands(entry.Value())
}

func parseMachineCommands(data []byte) (MachineCommands, error) {
	var raw struct {
		Commands *string           `json:"commands"`
		Catalog  []json.RawMessage `json:"catalog"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return MachineCommands{}, fmt.Errorf("failed to parse commands JSON: %w", err)
	}
	if raw.Commands == nil {
		return MachineCommands{}, fmt.Errorf("failed to parse commands JSON: missing commands field")
	}
	if raw.Catalog == nil {
		return MachineCommands{}, fmt.Errorf("failed to parse commands JSON: missing catalog field")
	}

	result := MachineCommands{Commands: *raw.Commands, Catalog: make([]MachineCommand, 0, len(raw.Catalog))}
	for index, rawEntry := range raw.Catalog {
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(rawEntry, &fields); err != nil {
			return MachineCommands{}, fmt.Errorf("failed to parse catalog[%d]: %w", index, err)
		}
		for _, field := range []string{"name", "signature", "doc", "safety"} {
			if _, ok := fields[field]; !ok {
				return MachineCommands{}, fmt.Errorf("failed to parse catalog[%d]: missing %s field", index, field)
			}
		}
		var entry MachineCommand
		if err := json.Unmarshal(rawEntry, &entry); err != nil {
			return MachineCommands{}, fmt.Errorf("failed to parse catalog[%d]: %w", index, err)
		}
		entry.DocPresent = true
		entry.SafetyPresent = true
		if entry.Name == "" || entry.Signature == "" {
			return MachineCommands{}, fmt.Errorf("failed to parse catalog[%d]: name and signature must be non-empty", index)
		}
		if entry.Safety != nil {
			var safetyFields map[string]json.RawMessage
			if err := json.Unmarshal(fields["safety"], &safetyFields); err != nil {
				return MachineCommands{}, fmt.Errorf("failed to parse catalog[%d] safety: %w", index, err)
			}
			for _, field := range []string{"summary", "hazards", "requires", "forbidden_when", "confirm"} {
				if _, ok := safetyFields[field]; !ok {
					return MachineCommands{}, fmt.Errorf("failed to parse catalog[%d] safety: missing %s field", index, field)
				}
			}
			if entry.Safety.Summary == "" || entry.Safety.Hazards == nil || entry.Safety.Confirm == nil {
				return MachineCommands{}, fmt.Errorf("failed to parse catalog[%d] safety: malformed required fields", index)
			}
		}
		result.Catalog = append(result.Catalog, entry)
	}
	return result, nil
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
