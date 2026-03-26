package nats

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	natsio "github.com/nats-io/nats.go"
)

// WatchEvent represents a single telemetry or event message from a machine.
type WatchEvent struct {
	Timestamp time.Time       `json:"timestamp"`
	Subject   string          `json:"subject"`
	MachineID string          `json:"machine_id"`
	Category  string          `json:"category"` // "tlm" or "evt"
	Topic     string          `json:"topic"`
	Data      json.RawMessage `json:"data"`
}

// WatchOpts configures which subjects SubscribeMachineSubjects subscribes to.
type WatchOpts struct {
	// Subjects limits output to these subject suffixes (e.g. "pos", "health").
	// Nil or empty means all subjects pass.
	Subjects map[string]struct{}
	// IncludeHeartbeat must be true to receive heartbeat messages.
	// Heartbeats are excluded by default because they are high-frequency
	// and already consumed by ListMachines.
	IncludeHeartbeat bool
}

// SubscribeMachineSubjects subscribes to puda.<id>.tlm.* and puda.<id>.evt.* for
// every machine ID in the slice and multiplexes all messages into a single
// channel.
func SubscribeMachineSubjects(ctx context.Context, nc *natsio.Conn, machineIDs []string, opts WatchOpts) (<-chan WatchEvent, error) {
	if len(machineIDs) == 0 {
		return nil, fmt.Errorf("at least one machine ID is required")
	}

	ch := make(chan WatchEvent, 64)

	handler := func(msg *natsio.Msg) {
		parts := strings.Split(msg.Subject, ".")
		if len(parts) < 4 {
			return
		}
		mid := parts[1]
		category := parts[2]
		topic := strings.Join(parts[3:], ".")

		if !opts.IncludeHeartbeat && topic == "heartbeat" {
			return
		}
		if len(opts.Subjects) > 0 {
			if _, ok := opts.Subjects[topic]; !ok {
				return
			}
		}

		var data json.RawMessage
		if json.Valid(msg.Data) {
			data = msg.Data
		} else {
			data, _ = json.Marshal(string(msg.Data))
		}

		evt := WatchEvent{
			Timestamp: time.Now().UTC(),
			Subject:   msg.Subject,
			MachineID: mid,
			Category:  category,
			Topic:     topic,
			Data:      data,
		}
		select {
		case ch <- evt:
		case <-ctx.Done():
		}
	}

	subs := make([]*natsio.Subscription, 0, len(machineIDs)*2)
	for _, id := range machineIDs {
		tlmSub, err := nc.Subscribe(fmt.Sprintf("puda.%s.tlm.*", id), handler)
		if err != nil {
			for _, s := range subs {
				s.Unsubscribe()
			}
			close(ch)
			return nil, fmt.Errorf("failed to subscribe to telemetry for %s: %w", id, err)
		}
		subs = append(subs, tlmSub)

		evtSub, err := nc.Subscribe(fmt.Sprintf("puda.%s.evt.*", id), handler)
		if err != nil {
			for _, s := range subs {
				s.Unsubscribe()
			}
			close(ch)
			return nil, fmt.Errorf("failed to subscribe to events for %s: %w", id, err)
		}
		subs = append(subs, evtSub)
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

// ListMachines subscribes to puda.*.tlm.heartbeat for the given duration
// and returns the unique machine IDs that were seen.
func ListMachines(nc *natsio.Conn, timeout time.Duration) ([]string, error) {
	seen := make(map[string]struct{})

	sub, err := nc.Subscribe("puda.*.tlm.heartbeat", func(msg *natsio.Msg) {
		parts := strings.Split(msg.Subject, ".")
		if len(parts) >= 2 {
			seen[parts[1]] = struct{}{}
		}
	})
	if err != nil {
		return nil, fmt.Errorf("failed to subscribe to heartbeat: %w", err)
	}
	defer sub.Unsubscribe()

	time.Sleep(timeout)

	machines := make([]string, 0, len(seen))
	for id := range seen {
		machines = append(machines, id)
	}
	return machines, nil
}

// GetMachineCommands retrieves the commands of a specific machine from KV store
func GetMachineCommands(nc *natsio.Conn, machineID string) error {
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}
	kvBucketName := fmt.Sprintf("MACHINE_COMMANDS_%s", strings.ReplaceAll(machineID, ".", "-"))
	kv, err := js.KeyValue(kvBucketName)
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

// GetSingleMachineState retrieves the state of a specific machine from KV store
func GetSingleMachineState(nc *natsio.Conn, machineID string) error {
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("failed to get JetStream context: %w", err)
	}

	kvBucketName := fmt.Sprintf("MACHINE_STATE_%s", strings.ReplaceAll(machineID, ".", "-"))

	kv, err := js.KeyValue(kvBucketName)
	if err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("KV bucket not found for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("KV bucket not found: %w", err)
	}

	entry, err := kv.Get(machineID)
	if err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("Could not find state for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("failed to get machine state: %w", err)
	}

	var state map[string]interface{}
	if err := json.Unmarshal(entry.Value(), &state); err != nil {
		errorResponse := map[string]string{
			"error": fmt.Sprintf("Failed to parse state JSON for %s: %v", machineID, err),
		}
		jsonBytes, _ := json.MarshalIndent(errorResponse, "", "  ")
		fmt.Println(string(jsonBytes))
		return fmt.Errorf("failed to parse state JSON: %w", err)
	}

	jsonBytes, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}
	fmt.Println(string(jsonBytes))

	return nil
}
