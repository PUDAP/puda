package nats

import (
	"fmt"
	"strconv"
	"strings"
)

func parseProtocolSteps(stepsExpr *string) ([]StepRange, error) {
	if stepsExpr == nil {
		return nil, nil
	}
	steps := strings.TrimSpace(*stepsExpr)
	if steps == "" {
		return nil, fmt.Errorf("--steps cannot be empty")
	}

	selectors := strings.Split(steps, ",")
	stepRanges := make([]StepRange, 0, len(selectors))
	for _, selector := range selectors {
		stepRange, err := parseProtocolStepRange(selector)
		if err != nil {
			return nil, err
		}
		stepRanges = append(stepRanges, stepRange)
	}
	return stepRanges, nil
}

func parseProtocolStepRange(value string) (StepRange, error) {
	steps := strings.TrimSpace(value)
	if steps == "" {
		return StepRange{}, fmt.Errorf("--steps contains an empty selector")
	}

	if !strings.Contains(steps, "-") {
		step, err := parsePositiveStep(steps)
		if err != nil {
			return StepRange{}, fmt.Errorf("invalid --steps value %q: %w", value, err)
		}
		return StepRange{StartStep: step, EndStep: step}, nil
	}

	if strings.Count(steps, "-") != 1 {
		return StepRange{}, fmt.Errorf("invalid --steps value %q: expected STEP, START-END, or START-", value)
	}

	parts := strings.SplitN(steps, "-", 2)
	if parts[0] == "" && parts[1] == "" {
		return StepRange{}, fmt.Errorf("invalid --steps value %q: expected STEP, START-END, or START-", value)
	}

	start := 1
	if parts[0] != "" {
		parsedStart, err := parsePositiveStep(parts[0])
		if err != nil {
			return StepRange{}, fmt.Errorf("invalid --steps start %q: %w", parts[0], err)
		}
		start = parsedStart
	}

	end := 0
	if parts[1] != "" {
		parsedEnd, err := parsePositiveStep(parts[1])
		if err != nil {
			return StepRange{}, fmt.Errorf("invalid --steps end %q: %w", parts[1], err)
		}
		end = parsedEnd
	}

	if end != 0 && end < start {
		return StepRange{}, fmt.Errorf("--steps end must be greater than or equal to start")
	}
	return StepRange{StartStep: start, EndStep: end}, nil
}

func parsePositiveStep(value string) (int, error) {
	step, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 0, err
	}
	if step < 1 {
		return 0, fmt.Errorf("step must be greater than 0")
	}
	return step, nil
}
