package nats

import (
	"reflect"
	"testing"
)

func TestParseProtocolStepsDefaultsToFullProtocol(t *testing.T) {
	got, err := parseProtocolSteps(nil)
	if err != nil {
		t.Fatalf("parseProtocolSteps(nil) returned error: %v", err)
	}
	if got != nil {
		t.Fatalf("parseProtocolSteps(nil) = %#v, want nil", got)
	}
}

func TestParseProtocolSteps(t *testing.T) {
	tests := []struct {
		name    string
		value   string
		want    []StepRange
		wantErr bool
	}{
		{
			name:  "single step",
			value: "3",
			want: []StepRange{
				{StartStep: 3, EndStep: 3},
			},
		},
		{
			name:  "bounded range",
			value: "2-5",
			want: []StepRange{
				{StartStep: 2, EndStep: 5},
			},
		},
		{
			name:  "open ended range",
			value: "2-",
			want: []StepRange{
				{StartStep: 2, EndStep: 0},
			},
		},
		{
			name:  "implicit start",
			value: "-5",
			want: []StepRange{
				{StartStep: 1, EndStep: 5},
			},
		},
		{
			name:  "comma separated selectors",
			value: "4,6-7,10-",
			want: []StepRange{
				{StartStep: 4, EndStep: 4},
				{StartStep: 6, EndStep: 7},
				{StartStep: 10, EndStep: 0},
			},
		},
		{
			name:    "empty",
			value:   "",
			wantErr: true,
		},
		{
			name:    "zero",
			value:   "0",
			wantErr: true,
		},
		{
			name:    "end before start",
			value:   "5-2",
			wantErr: true,
		},
		{
			name:    "too many ranges",
			value:   "1-2-3",
			wantErr: true,
		},
		{
			name:    "empty selector",
			value:   "1,,3",
			wantErr: true,
		},
		{
			name:    "not a number",
			value:   "two-five",
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseProtocolSteps(&tt.value)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("parseProtocolSteps(%q) returned no error", tt.value)
				}
				return
			}
			if err != nil {
				t.Fatalf("parseProtocolSteps(%q) returned error: %v", tt.value, err)
			}
			if !reflect.DeepEqual(got, tt.want) {
				t.Fatalf("parseProtocolSteps(%q) = %#v, want %#v", tt.value, got, tt.want)
			}
		})
	}
}
