package metrics

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type Summary struct {
	RequestedEdges     int64            `json:"requested_edges"`
	ConnectedEdges     int64            `json:"connected_edges"`
	PeakConnectedEdges int64            `json:"peak_connected_edges"`
	ConsumersCreated   int64            `json:"consumers_created"`
	MessagesSent       int64            `json:"messages_sent"`
	MessagesReceived   int64            `json:"messages_received"`
	Errors             int64            `json:"errors"`
	Reconnects         int64            `json:"reconnects"`
	ByMessageType      map[string]int64 `json:"messages_by_type"`
	ByReceivedType     map[string]int64 `json:"received_by_type"`
	ByErrorType        map[string]int64 `json:"errors_by_type"`
	GeneratedAt        string           `json:"generated_at"`
}

type Metrics struct {
	requested  atomic.Int64
	online     atomic.Int64
	peak       atomic.Int64
	consumers  atomic.Int64
	messages   atomic.Int64
	received   atomic.Int64
	errors     atomic.Int64
	reconnects atomic.Int64
	mu         sync.RWMutex
	byMessage  map[string]int64
	byReceived map[string]int64
	byError    map[string]int64
}

func New() *Metrics {
	return &Metrics{
		byMessage:  map[string]int64{},
		byReceived: map[string]int64{},
		byError:    map[string]int64{},
	}
}

func (m *Metrics) SetRequestedEdges(n int) { m.requested.Store(int64(n)) }
func (m *Metrics) EdgeConnected() {
	current := m.online.Add(1)
	for {
		peak := m.peak.Load()
		if current <= peak || m.peak.CompareAndSwap(peak, current) {
			break
		}
	}
}
func (m *Metrics) EdgeDisconnected() { m.online.Add(-1) }
func (m *Metrics) ConsumerCreated()  { m.consumers.Add(1) }
func (m *Metrics) Reconnect()        { m.reconnects.Add(1) }

func (m *Metrics) MessageSent(kind string) {
	m.messages.Add(1)
	m.mu.Lock()
	m.byMessage[kind]++
	m.mu.Unlock()
}

func (m *Metrics) MessageReceived(kind string) {
	m.received.Add(1)
	m.mu.Lock()
	m.byReceived[kind]++
	m.mu.Unlock()
}

func (m *Metrics) Error(kind string) {
	m.errors.Add(1)
	m.mu.Lock()
	m.byError[kind]++
	m.mu.Unlock()
}

func (m *Metrics) Summary() Summary {
	m.mu.RLock()
	messages := clone(m.byMessage)
	received := clone(m.byReceived)
	errors := clone(m.byError)
	m.mu.RUnlock()
	return Summary{
		RequestedEdges:     m.requested.Load(),
		ConnectedEdges:     m.online.Load(),
		PeakConnectedEdges: m.peak.Load(),
		ConsumersCreated:   m.consumers.Load(),
		MessagesSent:       m.messages.Load(),
		MessagesReceived:   m.received.Load(),
		Errors:             m.errors.Load(),
		Reconnects:         m.reconnects.Load(),
		ByMessageType:      messages,
		ByReceivedType:     received,
		ByErrorType:        errors,
		GeneratedAt:        time.Now().UTC().Format(time.RFC3339),
	}
}

func clone(in map[string]int64) map[string]int64 {
	out := make(map[string]int64, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}

func (m *Metrics) Prometheus() string {
	s := m.Summary()
	var b strings.Builder
	fmt.Fprintf(&b, "puda_loadgen_requested_edges %d\n", s.RequestedEdges)
	fmt.Fprintf(&b, "puda_loadgen_edges_online %d\n", s.ConnectedEdges)
	fmt.Fprintf(&b, "puda_loadgen_edges_peak %d\n", s.PeakConnectedEdges)
	fmt.Fprintf(&b, "puda_loadgen_consumers %d\n", s.ConsumersCreated)
	fmt.Fprintf(&b, "puda_loadgen_messages_sent_total %d\n", s.MessagesSent)
	fmt.Fprintf(&b, "puda_loadgen_messages_received_total %d\n", s.MessagesReceived)
	fmt.Fprintf(&b, "puda_loadgen_errors_total %d\n", s.Errors)
	fmt.Fprintf(&b, "puda_loadgen_reconnects_total %d\n", s.Reconnects)
	writeLabeled(&b, "puda_loadgen_messages_sent_total", s.ByMessageType)
	writeLabeled(&b, "puda_loadgen_messages_received_total", s.ByReceivedType)
	writeLabeled(&b, "puda_loadgen_errors_total", s.ByErrorType)
	return b.String()
}

func writeLabeled(b *strings.Builder, metric string, values map[string]int64) {
	keys := make([]string, 0, len(values))
	for k := range values {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		fmt.Fprintf(b, "%s{type=%q} %d\n", metric, k, values[k])
	}
}

func (m *Metrics) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		_, _ = w.Write([]byte(m.Prometheus()))
	})
	mux.HandleFunc("/summary", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(m.Summary())
	})
	return mux
}
