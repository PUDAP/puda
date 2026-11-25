package nats

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
	natsio "github.com/nats-io/nats.go"
)

func edgeReply(t *testing.T) *natsio.Msg {
	t.Helper()
	data, err := json.Marshal(puda.NATSMessage{
		Header:   puda.MessageHeader{MessageType: puda.MessageTypeResponse, MachineID: "m1"},
		Response: &puda.CommandResponse{Status: puda.StatusSuccess},
	})
	if err != nil {
		t.Fatal(err)
	}
	return &natsio.Msg{Subject: "_INBOX.x", Data: data}
}

func TestClassifyImmediateReply(t *testing.T) {
	if response, offline := classifyImmediateReply(edgeReply(t)); offline || response == nil || response.Response.Status != puda.StatusSuccess {
		t.Fatalf("success reply: response=%+v offline=%v", response, offline)
	}
	noResponders := &natsio.Msg{Header: natsio.Header{"Status": []string{"503"}}}
	if response, offline := classifyImmediateReply(noResponders); !offline || response != nil {
		t.Fatalf("no responders: response=%+v offline=%v", response, offline)
	}
	for _, junk := range []string{"+ACK", "-NAK", `{"stream":"X","seq":1}`, `{"header":{"machine_id":"m1"}}`, ""} {
		if response, offline := classifyImmediateReply(&natsio.Msg{Data: []byte(junk)}); response != nil || offline {
			t.Fatalf("junk %q: response=%+v offline=%v", junk, response, offline)
		}
	}
}

func TestWaitForImmediateReplyOffline(t *testing.T) {
	noResponders := &natsio.Msg{Header: natsio.Header{"Status": []string{"503"}}}
	_, err := waitForImmediateReply(context.Background(), inboxReplies(noResponders), time.Second)
	if !errors.Is(err, ErrMachineOffline) || !strings.Contains(err.Error(), "no responders: machine offline") {
		t.Fatalf("err=%v", err)
	}
}

// inboxReplies feeds msgs to waitForImmediateReply, then blocks until ctx ends.
func inboxReplies(msgs ...*natsio.Msg) func(context.Context) (*natsio.Msg, error) {
	return func(ctx context.Context) (*natsio.Msg, error) {
		if len(msgs) > 0 {
			msg := msgs[0]
			msgs = msgs[1:]
			return msg, nil
		}
		<-ctx.Done()
		return nil, ctx.Err()
	}
}

func TestWaitForImmediateReplySkipsJunkBeforeResponse(t *testing.T) {
	next := inboxReplies(&natsio.Msg{Data: []byte("+ACK")}, edgeReply(t))
	response, err := waitForImmediateReply(context.Background(), next, time.Second)
	if err != nil || response == nil {
		t.Fatalf("response=%+v err=%v", response, err)
	}
}

func TestWaitForImmediateReplyTimeoutIsOutcomeUnknown(t *testing.T) {
	_, err := waitForImmediateReply(context.Background(), inboxReplies(&natsio.Msg{Data: []byte("+ACK")}), 20*time.Millisecond)
	if err == nil || err.Error() != "no reply within 0.02s; outcome unknown (the command may have run); immediate commands are safe to retry" {
		t.Fatalf("err=%v", err)
	}
}

func TestWaitForImmediateReplyStopsOnCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := waitForImmediateReply(ctx, inboxReplies(), time.Hour)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context canceled", err)
	}
}

// immediateTestBroker starts a private loopback nats-server with JetStream.
// Set PUDA_NATS_SERVER (or PUDA_TEST_NATS_SERVER) to the binary to run it.
func immediateTestBroker(t *testing.T) *natsio.Conn {
	t.Helper()
	binary := os.Getenv("PUDA_NATS_SERVER")
	if binary == "" {
		binary = os.Getenv("PUDA_TEST_NATS_SERVER")
	}
	if binary == "" {
		t.Skip("set PUDA_NATS_SERVER to run loopback request/reply tests")
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	server := exec.Command(binary, "-a", "127.0.0.1", "-p", fmt.Sprint(port), "-js", "-sd", t.TempDir())
	if err := server.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = server.Process.Kill(); _ = server.Wait() })
	url := fmt.Sprintf("nats://127.0.0.1:%d", port)
	for deadline := time.Now().Add(5 * time.Second); time.Now().Before(deadline); time.Sleep(10 * time.Millisecond) {
		if nc, err := Connect(url, natsio.Timeout(100*time.Millisecond), natsio.NoReconnect()); err == nil {
			t.Cleanup(nc.Close)
			return nc
		}
	}
	t.Fatal("loopback broker did not become ready")
	return nil
}

func TestSendImmediateCommandOverRequestReply(t *testing.T) {
	nc := immediateTestBroker(t)

	started := time.Now()
	if _, err := SendResetCommand(nc, "ghost", "", "u", "user", 5, nil); !errors.Is(err, ErrMachineOffline) {
		t.Fatalf("offline machine err=%v", err)
	}
	if elapsed := time.Since(started); elapsed > 2*time.Second {
		t.Fatalf("no responders took %s, want an instant reply", elapsed)
	}

	// The edge answers on the inbox, sealed for the inbox subject.
	sub, err := nc.Subscribe("puda.m1.cmd.immediate", func(msg *natsio.Msg) {
		plain, err := Open(msg.Subject, msg.Data)
		if err != nil {
			return
		}
		var request puda.NATSMessage
		if json.Unmarshal(plain, &request) != nil {
			return
		}
		reply, _ := json.Marshal(puda.NATSMessage{
			Header:   puda.MessageHeader{MessageType: puda.MessageTypeResponse, MachineID: "m1"},
			Command:  request.Command,
			Response: &puda.CommandResponse{Status: puda.StatusSuccess},
		})
		sealed, _ := Seal(msg.Reply, reply)
		_ = msg.Respond([]byte("+ACK")) // unreadable replies are skipped
		_ = msg.Respond(sealed)
	})
	if err != nil {
		t.Fatal(err)
	}
	response, err := SendPauseCommand(nc, "m1", "", "u", "user", 5, nil)
	if err != nil || response.Response.Status != puda.StatusSuccess || response.Command == nil || response.Command.Name != puda.ImmediateCommandPause {
		t.Fatalf("response=%+v err=%v", response, err)
	}
	_ = sub.Unsubscribe()
}

func TestQueueFullIsRefusedWithoutRetryAndNothingIsDeleted(t *testing.T) {
	nc := immediateTestBroker(t)
	js, err := nc.JetStream()
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "infra", "nats", "jetstream", "streams", "COMMAND_QUEUE.json"))
	if err != nil {
		t.Fatal(err)
	}
	var cfg natsio.StreamConfig
	if err := json.Unmarshal(raw, &cfg); err != nil {
		t.Fatal(err)
	}
	if _, err := js.AddStream(&cfg); err != nil {
		t.Fatal(err)
	}
	if cfg.MaxMsgsPerSubject != 10 || !cfg.DiscardNewPerSubject {
		t.Fatalf("COMMAND_QUEUE: max_msgs_per_subject=%d discard_new_per_subject=%v, want 10/true", cfg.MaxMsgsPerSubject, cfg.DiscardNewPerSubject)
	}
	for i := 1; i <= 10; i++ {
		if _, err := js.Publish("puda.capped.cmd.queue", []byte(fmt.Sprintf("cmd%d", i))); err != nil {
			t.Fatalf("publish %d: %v", i, err)
		}
	}

	dispatcher := NewResponseDispatcher(js, "test-user")
	request := puda.CommandRequest{Name: "echo", StepNumber: 11, MachineID: "capped"}
	started := time.Now()
	_, err = SendQueueCommandWithContext(context.Background(), &sync.Mutex{}, js, dispatcher, request, "run-1", "test-user", "tester", nil)
	if !errors.Is(err, ErrQueueFull) {
		t.Fatalf("err = %v, want ErrQueueFull", err)
	}
	if !strings.Contains(err.Error(), "machine capped already has the maximum number of commands waiting") {
		t.Fatalf("message = %q", err)
	}
	if elapsed := time.Since(started); elapsed > 2*time.Second {
		t.Fatalf("took %s; a refused publish must not be retried", elapsed)
	}
	info, err := js.StreamInfo("COMMAND_QUEUE")
	if err != nil {
		t.Fatal(err)
	}
	if info.State.Msgs != 10 || info.State.FirstSeq != 1 {
		t.Fatalf("stream has %d messages from seq %d; want the original 10 from seq 1", info.State.Msgs, info.State.FirstSeq)
	}
}

func TestIsQueueFull(t *testing.T) {
	full := &natsio.APIError{Code: 503, ErrorCode: 10077, Description: "maximum messages per subject exceeded"}
	other := &natsio.APIError{Code: 503, ErrorCode: 10077, Description: "insufficient resources"}
	if !isQueueFull(fmt.Errorf("publish: %w", full)) || isQueueFull(other) || isQueueFull(errors.New("timeout")) {
		t.Fatal("isQueueFull misclassifies")
	}
}
