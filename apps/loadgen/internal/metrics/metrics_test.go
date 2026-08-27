package metrics

import (
	"strings"
	"testing"
)

func TestPrometheusSnapshot(t *testing.T) {
	m := New()
	m.SetRequestedEdges(100)
	m.EdgeConnected()
	m.ConsumerCreated()
	m.MessageSent("heartbeat")
	m.MessageReceived("queue_command")
	m.Error("connect")

	body := m.Prometheus()
	for _, want := range []string{
		"puda_loadgen_requested_edges 100",
		"puda_loadgen_edges_online 1",
		"puda_loadgen_edges_peak 1",
		"puda_loadgen_consumers 1",
		`puda_loadgen_messages_sent_total{type="heartbeat"} 1`,
		`puda_loadgen_messages_received_total{type="queue_command"} 1`,
		`puda_loadgen_errors_total{type="connect"} 1`,
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("metrics missing %q:\n%s", want, body)
		}
	}
}

func TestSummaryUsesCurrentCounters(t *testing.T) {
	m := New()
	m.SetRequestedEdges(2)
	m.EdgeConnected()
	m.EdgeConnected()
	m.ConsumerCreated()
	m.MessageSent("heartbeat")
	m.MessageReceived("queue_command")

	s := m.Summary()
	if s.RequestedEdges != 2 || s.ConnectedEdges != 2 || s.PeakConnectedEdges != 2 || s.ConsumersCreated != 1 || s.MessagesSent != 1 || s.MessagesReceived != 1 {
		t.Fatalf("unexpected summary: %+v", s)
	}
}
