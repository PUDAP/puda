package nats

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	natsio "github.com/nats-io/nats.go"
)

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

// SubscribeMachineSubjects subscribes to puda.<id>.> for every machine ID in
// the slice, or puda.*.> when machineIDs is empty. It captures machine traffic
// and multiplexes all messages into a single channel.
func SubscribeMachineSubjects(ctx context.Context, nc *natsio.Conn, machineIDs []string, opts WatchOpts) (<-chan WatchEvent, error) {
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
			catTopic := category + "." + topic
			matched := false
			for filter := range opts.Subjects {
				if catTopic == filter || strings.HasPrefix(catTopic, filter+".") {
					matched = true
					break
				}
			}
			if !matched {
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

	subjects := make([]string, 0, len(machineIDs))
	if len(machineIDs) == 0 {
		subjects = append(subjects, "puda.*.>")
	} else {
		for _, id := range machineIDs {
			subjects = append(subjects, fmt.Sprintf("puda.%s.>", id))
		}
	}

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

// GetMachineState retrieves the state of a specific machine from KV store.
func GetMachineState(nc *natsio.Conn, machineID string) (json.RawMessage, error) {
	js, err := nc.JetStream()
	if err != nil {
		return nil, fmt.Errorf("failed to get JetStream context: %w", err)
	}

	kvBucketName := fmt.Sprintf("MACHINE_STATE_%s", strings.ReplaceAll(machineID, ".", "-"))

	kv, err := js.KeyValue(kvBucketName)
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
