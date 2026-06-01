package cli

import (
	"errors"
	"testing"
)

func TestIsCommandLineError(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want bool
	}{
		{
			name: "argument validation error",
			err:  errors.New("accepts 1 arg(s), received 0"),
			want: true,
		},
		{
			name: "unknown flag error",
			err:  errors.New("unknown flag: --bogus"),
			want: true,
		},
		{
			name: "runtime command response error",
			err:  errors.New("reset failed: Unknown or restricted command: reset"),
			want: false,
		},
		{
			name: "runtime connection error",
			err:  errors.New("failed to connect to NATS: nats: no servers available for connection"),
			want: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := isCommandLineError(tt.err); got != tt.want {
				t.Fatalf("isCommandLineError() = %v, want %v", got, tt.want)
			}
		})
	}
}
