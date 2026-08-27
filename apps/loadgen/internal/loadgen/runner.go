package loadgen

import (
	"context"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/PUDAP/puda/apps/loadgen/internal/config"
	"github.com/PUDAP/puda/apps/loadgen/internal/edge"
	"github.com/PUDAP/puda/apps/loadgen/internal/fleet"
	"github.com/PUDAP/puda/apps/loadgen/internal/metrics"
	"github.com/nats-io/nats.go"
)

type virtualEdge struct {
	id string
	nc *nats.Conn
	js nats.JetStreamContext
}

type consumerRef struct {
	edge             virtualEdge
	queueDurable     string
	immediateDurable string
}

type Runner struct {
	cfg         config.Config
	metrics     *metrics.Metrics
	edges       []virtualEdge
	conns       []*nats.Conn
	wg          sync.WaitGroup
	cancel      context.CancelFunc
	consumerMu  sync.Mutex
	consumers   []consumerRef
	commandStep atomic.Int64
}

func New(cfg config.Config, m *metrics.Metrics) *Runner {
	m.SetRequestedEdges(cfg.Edges)
	return &Runner{cfg: cfg, metrics: m}
}

func connectionCount(cfg config.Config) int {
	if cfg.Mode == config.ModeFullFidelity {
		return cfg.Edges
	}
	if cfg.Connections > cfg.Edges {
		return cfg.Edges
	}
	return cfg.Connections
}

func needsConsumers(s config.Scenario) bool {
	return s == config.ScenarioConsumers || s == config.ScenarioSoak
}

func needsHeartbeat(s config.Scenario) bool {
	return s == config.ScenarioHeartbeat || s == config.ScenarioTelemetry || s == config.ScenarioSoak
}

func needsFullTelemetry(s config.Scenario) bool {
	return s == config.ScenarioTelemetry || s == config.ScenarioSoak
}

func (r *Runner) Run(ctx context.Context) error {
	runCtx, cancel := context.WithCancel(ctx)
	r.cancel = cancel
	if err := r.connect(runCtx); err != nil {
		r.Close()
		return err
	}
	if needsConsumers(r.cfg.Scenario) {
		if err := r.setupConsumers(runCtx); err != nil {
			r.Close()
			return err
		}
	}
	if needsHeartbeat(r.cfg.Scenario) {
		r.publishHeartbeat()
		r.startPublisher(runCtx, r.cfg.HeartbeatInterval, r.publishHeartbeat)
	}
	if needsFullTelemetry(r.cfg.Scenario) {
		r.publishPosition()
		r.publishHealth()
		r.startPublisher(runCtx, r.cfg.PositionInterval, r.publishPosition)
		r.startPublisher(runCtx, r.cfg.HealthInterval, r.publishHealth)
	}
	if r.cfg.CommandInterval > 0 {
		r.startCommandPublisher(runCtx)
	}
	<-runCtx.Done()
	r.Close()
	return nil
}

func (r *Runner) connect(ctx context.Context) error {
	ids := fleet.IDs(r.cfg.Prefix, r.cfg.StartIndex, r.cfg.Edges)
	count := connectionCount(r.cfg)
	url := strings.Join(r.cfg.NATSServers, ",")
	pool := make([]*nats.Conn, 0, count)
	step := time.Duration(0)
	if r.cfg.RampDuration > 0 && count > 1 {
		step = r.cfg.RampDuration / time.Duration(count-1)
	}
	for i := 0; i < count; i++ {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		name := fmt.Sprintf("puda-loadgen-%d", i+1)
		nc, err := nats.Connect(
			url,
			nats.Name(name),
			nats.Timeout(r.cfg.ConnectTimeout),
			nats.MaxReconnects(-1),
			nats.ReconnectWait(time.Second),
			nats.NoEcho(),
			nats.ReconnectHandler(func(_ *nats.Conn) { r.metrics.Reconnect() }),
		)
		if err != nil {
			r.metrics.Error("connect")
			return fmt.Errorf("connect %d/%d: %w", i+1, count, err)
		}
		pool = append(pool, nc)
		r.conns = append(r.conns, nc)
		if step > 0 && i+1 < count {
			timer := time.NewTimer(step)
			select {
			case <-ctx.Done():
				timer.Stop()
				return ctx.Err()
			case <-timer.C:
			}
		}
	}

	r.edges = make([]virtualEdge, len(ids))
	for i, id := range ids {
		nc := pool[i%len(pool)]
		js, err := nc.JetStream()
		if err != nil {
			r.metrics.Error("jetstream_context")
			return fmt.Errorf("JetStream context for %s: %w", id, err)
		}
		r.edges[i] = virtualEdge{id: id, nc: nc, js: js}
		r.metrics.EdgeConnected()
	}
	log.Printf("connected %d virtual edges using %d NATS connections", len(r.edges), len(pool))
	return nil
}

func (r *Runner) setupConsumers(ctx context.Context) error {
	jobs := make(chan int)
	errCh := make(chan error, 1)
	workers := r.cfg.SetupConcurrency
	if workers > len(r.edges) {
		workers = len(r.edges)
	}
	var wg sync.WaitGroup
	for worker := 0; worker < workers; worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				if err := r.setupEdgeConsumers(ctx, i); err != nil {
					select {
					case errCh <- err:
					default:
					}
					return
				}
			}
		}()
	}
	for i := range r.edges {
		select {
		case <-ctx.Done():
			close(jobs)
			wg.Wait()
			r.cleanupConsumers()
			return ctx.Err()
		case err := <-errCh:
			close(jobs)
			wg.Wait()
			r.cleanupConsumers()
			return err
		case jobs <- i:
		}
	}
	close(jobs)
	wg.Wait()
	select {
	case err := <-errCh:
		r.cleanupConsumers()
		return err
	default:
	}
	log.Printf("created %d command consumers", len(r.edges)*2)
	return nil
}

func (r *Runner) setupEdgeConsumers(ctx context.Context, index int) error {
	e := r.edges[index]
	queueDurable := "load_queue_" + e.id
	queueSub, err := e.js.PullSubscribe(
		edge.QueueSubject(e.id), queueDurable,
		nats.BindStream(r.cfg.QueueStream), nats.ManualAck(),
	)
	if err != nil {
		r.metrics.Error("queue_consumer")
		return fmt.Errorf("queue consumer for %s: %w", e.id, err)
	}

	immediateDurable := "load_immediate_" + e.id
	_, err = e.js.Subscribe(
		edge.ImmediateSubject(e.id),
		func(msg *nats.Msg) {
			r.metrics.MessageReceived("immediate_command")
			r.handleCommand(e, msg, "immediate_response", edge.ImmediateResponseSubject(e.id))
		},
		nats.Durable(immediateDurable),
		nats.BindStream(r.cfg.ImmediateStream),
		nats.ManualAck(),
		nats.DeliverAll(),
	)
	if err != nil {
		r.metrics.Error("immediate_consumer")
		_ = queueSub.Unsubscribe()
		_ = e.js.DeleteConsumer(r.cfg.QueueStream, queueDurable)
		return fmt.Errorf("immediate consumer for %s: %w", e.id, err)
	}

	r.consumerMu.Lock()
	r.consumers = append(r.consumers, consumerRef{edge: e, queueDurable: queueDurable, immediateDurable: immediateDurable})
	r.consumerMu.Unlock()
	r.metrics.ConsumerCreated()
	r.metrics.ConsumerCreated()
	r.wg.Add(1)
	go r.pullLoop(ctx, e, queueSub)
	return nil
}

func (r *Runner) cleanupConsumers() {
	r.consumerMu.Lock()
	refs := r.consumers
	r.consumers = nil
	r.consumerMu.Unlock()
	if len(refs) == 0 {
		return
	}
	jobs := make(chan consumerRef)
	workers := r.cfg.SetupConcurrency
	if workers > len(refs) {
		workers = len(refs)
	}
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for ref := range jobs {
				if err := ref.edge.js.DeleteConsumer(r.cfg.QueueStream, ref.queueDurable); err != nil {
					r.metrics.Error("queue_consumer_cleanup")
				}
				if err := ref.edge.js.DeleteConsumer(r.cfg.ImmediateStream, ref.immediateDurable); err != nil {
					r.metrics.Error("immediate_consumer_cleanup")
				}
			}
		}()
	}
	for _, ref := range refs {
		jobs <- ref
	}
	close(jobs)
	wg.Wait()
	log.Printf("deleted %d command consumers", len(refs)*2)
}

func (r *Runner) pullLoop(ctx context.Context, e virtualEdge, sub *nats.Subscription) {
	defer r.wg.Done()
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		msgs, err := sub.Fetch(1, nats.MaxWait(r.cfg.QueueFetchWait))
		if err != nil {
			if !shouldRecordFetchError(ctx, err) {
				select {
				case <-ctx.Done():
					return
				default:
					continue
				}
			}
			r.metrics.Error("queue_fetch")
			select {
			case <-ctx.Done():
				return
			case <-time.After(time.Second):
			}
			continue
		}
		for _, msg := range msgs {
			r.metrics.MessageReceived("queue_command")
			r.handleCommand(e, msg, "queue_response", edge.QueueResponseSubject(e.id))
		}
	}
}

func (r *Runner) handleCommand(e virtualEdge, msg *nats.Msg, metricType, responseSubject string) {
	payload, err := edge.SuccessResponse(msg.Data)
	if err != nil {
		r.metrics.Error("command_decode")
		_ = msg.Term()
		return
	}
	if _, err := e.js.Publish(responseSubject, payload); err != nil {
		r.metrics.Error("response_publish")
		_ = msg.Nak()
		return
	}
	r.metrics.MessageSent(metricType)
	_ = msg.Ack()
}

func shouldRecordFetchError(ctx context.Context, err error) bool {
	if errors.Is(err, nats.ErrTimeout) {
		return false
	}
	select {
	case <-ctx.Done():
		return false
	default:
		return true
	}
}

func (r *Runner) startCommandPublisher(ctx context.Context) {
	r.wg.Add(1)
	go func() {
		defer r.wg.Done()
		ticker := time.NewTicker(r.cfg.CommandInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				r.publishCommandBatch(ctx)
			}
		}
	}()
}

func (r *Runner) publishCommandBatch(ctx context.Context) {
	step := int(r.commandStep.Add(1))
	runID := fmt.Sprintf("loadgen-%d-%d", time.Now().UnixNano(), step)
	jobs := make(chan virtualEdge)
	workers := r.cfg.SetupConcurrency
	if workers > len(r.edges) {
		workers = len(r.edges)
	}
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for e := range jobs {
				payload, err := edge.CommandPayload(e.id, runID, step, "loadgen_ping")
				if err != nil {
					r.metrics.Error("command_encode")
					continue
				}
				if _, err := e.js.Publish(edge.QueueSubject(e.id), payload); err != nil {
					r.metrics.Error("queue_command_publish")
				} else {
					r.metrics.MessageSent("queue_command")
				}
				if _, err := e.js.Publish(edge.ImmediateSubject(e.id), payload); err != nil {
					r.metrics.Error("immediate_command_publish")
				} else {
					r.metrics.MessageSent("immediate_command")
				}
			}
		}()
	}
	for _, e := range r.edges {
		select {
		case <-ctx.Done():
			close(jobs)
			wg.Wait()
			return
		case jobs <- e:
		}
	}
	close(jobs)
	wg.Wait()
}

func (r *Runner) startPublisher(ctx context.Context, interval time.Duration, publish func()) {
	r.wg.Add(1)
	go func() {
		defer r.wg.Done()
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				publish()
			}
		}
	}()
}

func (r *Runner) publishHeartbeat() {
	payload, _ := edge.HeartbeatPayload()
	r.publish("heartbeat", payload, edge.HeartbeatSubject)
}

func (r *Runner) publishPosition() {
	payload, _ := edge.PositionPayload(0, 0, 0)
	r.publish("position", payload, edge.PositionSubject)
}

func (r *Runner) publishHealth() {
	payload, _ := edge.HealthPayload(0, 0)
	r.publish("health", payload, edge.HealthSubject)
}

func (r *Runner) publish(kind string, payload []byte, subject func(string) string) {
	for i := range r.edges {
		e := &r.edges[i]
		if err := e.nc.Publish(subject(e.id), payload); err != nil {
			r.metrics.Error("publish_" + kind)
			continue
		}
		r.metrics.MessageSent(kind)
	}
}

func (r *Runner) Close() {
	if r.cancel != nil {
		r.cancel()
	}
	if r.cfg.CleanupConsumers {
		r.cleanupConsumers()
	}
	r.wg.Wait()
	for _, nc := range r.conns {
		nc.Close()
	}
	for range r.edges {
		r.metrics.EdgeDisconnected()
	}
	r.edges = nil
	r.conns = nil
}
