package nats

import (
	"encoding/json"
	"fmt"
	"log"
	"sync"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	"github.com/nats-io/nats.go"
)

const (
	streamResponseImmediate = "RESPONSE_IMMEDIATE"
	streamResponseQueue     = "RESPONSE_QUEUE"
)

type responseKey struct {
	runID      string
	stepNumber int
}

// ResponseDispatcher manages a single long-lived JetStream subscription per
// response stream (immediate + queue) and routes incoming responses to the
// correct caller via a correlation map keyed on (runID, stepNumber).
type ResponseDispatcher struct {
	js           nats.JetStreamContext
	userID       string
	mu           sync.Mutex
	pending      map[responseKey]chan *puda.NATSMessage
	immediateSub *nats.Subscription
	queueSub     *nats.Subscription
}

func NewResponseDispatcher(js nats.JetStreamContext, userID string) *ResponseDispatcher {
	return &ResponseDispatcher{
		js:      js,
		userID:  userID,
		pending: make(map[responseKey]chan *puda.NATSMessage),
	}
}

// Start creates the two durable push subscriptions (one per response stream).
// Both use the same durable name scoped to the user: user-<userID>.
func (d *ResponseDispatcher) Start() error {
	durable := fmt.Sprintf("user-%s", d.userID)

	handler := func(msg *nats.Msg) {
		var response puda.NATSMessage
		if err := json.Unmarshal(msg.Data, &response); err != nil {
			log.Printf("Failed to unmarshal response: %v", err)
			msg.Ack()
			return
		}

		var runID string
		if response.Header.RunID != nil {
			runID = *response.Header.RunID
		}
		var stepNumber int
		if response.Command != nil {
			stepNumber = response.Command.StepNumber
		}

		key := responseKey{runID: runID, stepNumber: stepNumber}

		d.mu.Lock()
		ch, ok := d.pending[key]
		d.mu.Unlock()

		if ok {
			select {
			case ch <- &response:
			default:
			}
		}
		msg.Ack()
	}

	var err error
	d.immediateSub, err = d.js.Subscribe(
		"puda.*.cmd.response.immediate",
		handler,
		nats.Durable(durable),
		nats.DeliverNew(),
		nats.BindStream(streamResponseImmediate),
	)
	if err != nil {
		return fmt.Errorf("failed to subscribe to immediate responses: %w", err)
	}

	d.queueSub, err = d.js.Subscribe(
		"puda.*.cmd.response.queue",
		handler,
		nats.Durable(durable),
		nats.DeliverNew(),
		nats.BindStream(streamResponseQueue),
	)
	if err != nil {
		d.immediateSub.Unsubscribe()
		return fmt.Errorf("failed to subscribe to queue responses: %w", err)
	}

	return nil
}

func (d *ResponseDispatcher) Close() {
	if d.immediateSub != nil {
		d.immediateSub.Unsubscribe()
	}
	if d.queueSub != nil {
		d.queueSub.Unsubscribe()
	}
}

// Register returns a buffered channel that will receive the response matching
// the given (runID, stepNumber) pair. Caller must defer Unregister.
func (d *ResponseDispatcher) Register(runID string, stepNumber int) <-chan *puda.NATSMessage {
	ch := make(chan *puda.NATSMessage, 1)
	key := responseKey{runID: runID, stepNumber: stepNumber}
	d.mu.Lock()
	d.pending[key] = ch
	d.mu.Unlock()
	return ch
}

func (d *ResponseDispatcher) Unregister(runID string, stepNumber int) {
	key := responseKey{runID: runID, stepNumber: stepNumber}
	d.mu.Lock()
	delete(d.pending, key)
	d.mu.Unlock()
}
