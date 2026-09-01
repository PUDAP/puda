package nats

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/PUDAP/puda/apps/cli/internal/puda"
)

func TestRequireSuccessfulQueueResponseFailsClosed(t *testing.T) {
	for _, status := range []puda.CommandResponseStatus{"", "unknown", puda.StatusError} {
		response := &puda.NATSMessage{Response: &puda.CommandResponse{Status: status}}
		if err := requireSuccessfulQueueResponse(response); err == nil {
			t.Fatalf("accepted queued response status %q", status)
		}
	}
	if err := requireSuccessfulQueueResponse(&puda.NATSMessage{Response: &puda.CommandResponse{Status: puda.StatusSuccess}}); err != nil {
		t.Fatal(err)
	}
}

func TestRequireSuccessfulLifecycleResponseFailsClosed(t *testing.T) {
	tests := []struct {
		name     string
		response *puda.NATSMessage
	}{
		{name: "nil message", response: nil},
		{name: "nil response", response: &puda.NATSMessage{}},
		{name: "empty status", response: &puda.NATSMessage{Response: &puda.CommandResponse{}}},
		{name: "unknown status", response: &puda.NATSMessage{Response: &puda.CommandResponse{Status: puda.CommandResponseStatus("unknown")}}},
		{name: "error status", response: &puda.NATSMessage{Response: &puda.CommandResponse{Status: puda.StatusError}}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if err := requireSuccessfulLifecycleResponse("START", test.response); err == nil {
				t.Fatalf("accepted malformed response: %+v", test.response)
			}
		})
	}
}

func TestRequireSuccessfulLifecycleResponseAcceptsOnlySuccess(t *testing.T) {
	response := &puda.NATSMessage{Response: &puda.CommandResponse{Status: puda.StatusSuccess}}
	if err := requireSuccessfulLifecycleResponse("COMPLETE", response); err != nil {
		t.Fatal(err)
	}
}

func TestCommandPayloadDoesNotSendProtocolSafetyToEdge(t *testing.T) {
	request := puda.CommandRequest{
		Name:      "move",
		MachineID: "machine",
		Safety:    &puda.CommandSafety{Summary: "Motion risk.", Confirm: true},
	}
	payload := BuildCommandPayload(request, "machine", "run", "user", "name")
	if payload.Command == nil {
		t.Fatal("command payload is nil")
	}
	if payload.Command.Safety != nil {
		t.Fatalf("protocol safety leaked into edge command payload: %+v", payload.Command.Safety)
	}
}

func TestPublishQueueCommandInterlocksCancellationWithActualPublish(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	var interlock sync.Mutex
	publishEntered := make(chan struct{})
	releasePublish := make(chan struct{})
	published := make(chan error, 1)
	go func() {
		published <- publishQueueCommandWithCancellation(ctx, &interlock, func() error {
			close(publishEntered)
			<-releasePublish
			return nil
		})
	}()
	<-publishEntered

	cancelled := make(chan struct{})
	cancelAttempted := make(chan struct{})
	go func() {
		close(cancelAttempted)
		interlock.Lock()
		cancel()
		interlock.Unlock()
		close(cancelled)
	}()
	<-cancelAttempted
	select {
	case <-cancelled:
		t.Fatal("cancellation completed while publication was in progress")
	default:
	}
	close(releasePublish)
	if err := <-published; err != nil {
		t.Fatal(err)
	}
	<-cancelled
}

func TestPublishQueueCommandDoesNotPublishAfterInterlockedCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	var interlock sync.Mutex
	interlock.Lock()
	cancel()
	interlock.Unlock()
	called := false

	err := publishQueueCommandWithCancellation(ctx, &interlock, func() error {
		called = true
		return nil
	})

	if !errors.Is(err, context.Canceled) || called {
		t.Fatalf("error = %v, publish called = %v", err, called)
	}
}

func TestPublishStartDoesNotPublishAfterInterlockedCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	var interlock sync.Mutex
	interlock.Lock()
	cancel()
	interlock.Unlock()
	attempted := false
	published := false

	err := publishStartCommandWithCancellation(ctx, &interlock, func() {
		attempted = true
	}, func() error {
		published = true
		return nil
	})

	if !errors.Is(err, context.Canceled) || attempted || published {
		t.Fatalf("error = %v, attempted = %v, published = %v", err, attempted, published)
	}
}

func TestPublishStartReleasesInterlockAfterPublication(t *testing.T) {
	var interlock sync.Mutex
	if err := publishStartCommandWithCancellation(context.Background(), &interlock, nil, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	if !interlock.TryLock() {
		t.Fatal("publication interlock remained held after publish returned")
	}
	interlock.Unlock()
}

func TestWaitForImmediateResponseStopsOnCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := waitForImmediateResponse(ctx, make(chan *puda.NATSMessage), time.Hour)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context canceled", err)
	}
}

func TestAttemptedStartIsEligibleForCleanupWhenResponseIsLost(t *testing.T) {
	completed := []string(nil)
	cleanup := newStartedMachineCleanup(func(machineIDs []string) error {
		completed = append(completed, machineIDs...)
		return nil
	})

	err := publishStartCommandWithCancellation(context.Background(), &sync.Mutex{}, func() {
		cleanup.markStarted("machine-1")
	}, func() error {
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	// No response is observed after the successful publication.
	if cleanupErr := cleanup.complete(); cleanupErr != nil {
		t.Fatal(cleanupErr)
	}

	if len(completed) != 1 || completed[0] != "machine-1" {
		t.Fatalf("completed machines = %v", completed)
	}
}

func TestStartedMachineCleanupCompletesEachMachineOnlyOnce(t *testing.T) {
	var mutex sync.Mutex
	completed := make(map[string]int)
	cleanup := newStartedMachineCleanup(func(machineIDs []string) error {
		mutex.Lock()
		defer mutex.Unlock()
		for _, machineID := range machineIDs {
			completed[machineID]++
		}
		return nil
	})
	cleanup.markStarted("machine-1")
	cleanup.markStarted("machine-2")

	var wait sync.WaitGroup
	for range 8 {
		wait.Add(1)
		go func() {
			defer wait.Done()
			if err := cleanup.complete(); err != nil {
				t.Errorf("cleanup failed: %v", err)
			}
		}()
	}
	wait.Wait()

	if completed["machine-1"] != 1 || completed["machine-2"] != 1 || len(completed) != 2 {
		t.Fatalf("completion counts = %v", completed)
	}
}

func TestCompleteMachinesAggregatesFailures(t *testing.T) {
	first := errors.New("first COMPLETE failed")
	second := errors.New("second COMPLETE failed")
	err := completeMachines([]string{"machine-1", "machine-2"}, func(machineID string) error {
		if machineID == "machine-1" {
			return first
		}
		return second
	})

	if !errors.Is(err, first) || !errors.Is(err, second) {
		t.Fatalf("error = %v, want both COMPLETE failures", err)
	}
}

func TestStartedMachineCleanupReturnsCachedErrorOnlyOnce(t *testing.T) {
	want := errors.New("COMPLETE failed")
	calls := 0
	cleanup := newStartedMachineCleanup(func([]string) error {
		calls++
		return want
	})
	cleanup.markStarted("machine-1")

	first := cleanup.complete()
	second := cleanup.complete()
	if calls != 1 || !errors.Is(first, want) || !errors.Is(second, want) {
		t.Fatalf("calls = %d, first = %v, second = %v", calls, first, second)
	}
}

func TestJoinProtocolAndCleanupErrorsPreservesExistingFailure(t *testing.T) {
	runErr := errors.New("queue failed")
	cleanupErr := errors.New("COMPLETE failed")
	err := joinProtocolAndCleanupErrors(runErr, cleanupErr)
	if !errors.Is(err, runErr) || !errors.Is(err, cleanupErr) {
		t.Fatalf("error = %v, want queue and COMPLETE failures", err)
	}
}

func TestJoinProtocolAndCleanupErrorsReturnsCleanupFailureAfterSuccess(t *testing.T) {
	cleanupErr := errors.New("COMPLETE failed")
	if err := joinProtocolAndCleanupErrors(nil, cleanupErr); !errors.Is(err, cleanupErr) {
		t.Fatalf("error = %v, want %v", err, cleanupErr)
	}
}

func TestRequestStepConfirmationCallsGateBeforeBatch(t *testing.T) {
	commands := []puda.CommandRequest{{StepNumber: 3, MachineID: "machine", Name: "move"}}
	called := false
	err := requestStepConfirmation(context.Background(), 3, commands, func(_ context.Context, step int, got []puda.CommandRequest) error {
		called = true
		if step != 3 || len(got) != 1 || got[0].Name != "move" {
			t.Fatalf("step=%d commands=%+v", step, got)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if !called {
		t.Fatal("confirmation gate was not called")
	}
}

func TestRequestStepConfirmationStopsBatchWhenGateRejects(t *testing.T) {
	want := errors.New("not confirmed")
	err := requestStepConfirmation(context.Background(), 1, []puda.CommandRequest{{StepNumber: 1}}, func(context.Context, int, []puda.CommandRequest) error {
		return want
	})
	if !errors.Is(err, want) {
		t.Fatalf("error = %v, want %v", err, want)
	}
}

func TestRequestStepConfirmationAllowsNilGate(t *testing.T) {
	if err := requestStepConfirmation(context.Background(), 1, []puda.CommandRequest{{StepNumber: 1}}, nil); err != nil {
		t.Fatal(err)
	}
}

func TestRequestStepConfirmationRejectsCancelledContextWithoutCallingGate(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	called := false
	err := requestStepConfirmation(ctx, 1, []puda.CommandRequest{{StepNumber: 1}}, func(context.Context, int, []puda.CommandRequest) error {
		called = true
		return nil
	})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context canceled", err)
	}
	if called {
		t.Fatal("confirmation gate called after cancellation")
	}
}
