package config

import (
	"flag"
	"fmt"
	"io"
	"net/url"
	"strings"
	"time"
)

type Mode string

const (
	ModeFullFidelity Mode = "full-fidelity"
	ModeMultiplexed  Mode = "multiplexed"
)

type Scenario string

const (
	ScenarioConnections Scenario = "connections"
	ScenarioConsumers   Scenario = "consumers"
	ScenarioHeartbeat   Scenario = "heartbeat"
	ScenarioTelemetry   Scenario = "telemetry"
	ScenarioSoak        Scenario = "soak"
)

type Config struct {
	Edges             int
	Prefix            string
	StartIndex        int
	NATSServers       []string
	Mode              Mode
	Connections       int
	Scenario          Scenario
	Duration          time.Duration
	RampDuration      time.Duration
	HeartbeatInterval time.Duration
	PositionInterval  time.Duration
	HealthInterval    time.Duration
	QueueStream       string
	ImmediateStream   string
	MetricsAddress    string
	ReportPath        string
	ConnectTimeout    time.Duration
	SetupConcurrency  int
	QueueFetchWait    time.Duration
	CleanupConsumers  bool
	CommandInterval   time.Duration
}

func Parse(args []string) (Config, error) {
	fs := flag.NewFlagSet("puda-loadgen", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	var cfg Config
	var servers, mode, scenario string
	fs.IntVar(&cfg.Edges, "edges", 1000, "number of virtual edges")
	fs.StringVar(&cfg.Prefix, "prefix", "load", "machine ID prefix")
	fs.IntVar(&cfg.StartIndex, "start-index", 1, "first numeric machine ID")
	fs.StringVar(&servers, "nats-servers", "nats://localhost:4222", "comma-separated NATS URLs")
	fs.StringVar(&mode, "mode", string(ModeFullFidelity), "full-fidelity or multiplexed")
	fs.IntVar(&cfg.Connections, "connections", 16, "connection pool size in multiplexed mode")
	fs.StringVar(&scenario, "scenario", string(ScenarioConnections), "connections, consumers, heartbeat, telemetry, or soak")
	fs.DurationVar(&cfg.Duration, "duration", 0, "run duration; zero means until interrupted")
	fs.DurationVar(&cfg.RampDuration, "ramp-duration", 0, "time over which connections are created")
	fs.DurationVar(&cfg.HeartbeatInterval, "heartbeat-interval", 10*time.Second, "heartbeat publication interval")
	fs.DurationVar(&cfg.PositionInterval, "position-interval", 30*time.Second, "position publication interval")
	fs.DurationVar(&cfg.HealthInterval, "health-interval", 60*time.Second, "health publication interval")
	fs.StringVar(&cfg.QueueStream, "queue-stream", "COMMAND_QUEUE", "queue command stream")
	fs.StringVar(&cfg.ImmediateStream, "immediate-stream", "COMMAND_IMMEDIATE", "immediate command stream")
	fs.StringVar(&cfg.MetricsAddress, "metrics-address", "127.0.0.1:9090", "Prometheus HTTP listen address; empty disables")
	fs.StringVar(&cfg.ReportPath, "report", "", "optional JSON summary output path")
	fs.DurationVar(&cfg.ConnectTimeout, "connect-timeout", 5*time.Second, "NATS connection timeout")
	fs.IntVar(&cfg.SetupConcurrency, "setup-concurrency", 64, "parallel JetStream consumer setup workers")
	fs.DurationVar(&cfg.QueueFetchWait, "queue-fetch-wait", 30*time.Second, "maximum wait for each queue-consumer fetch")
	fs.BoolVar(&cfg.CleanupConsumers, "cleanup-consumers", true, "delete load-test consumers during shutdown")
	fs.DurationVar(&cfg.CommandInterval, "command-interval", 0, "publish one queue and one immediate command per edge at this interval; zero disables")
	if err := fs.Parse(args); err != nil {
		return Config{}, err
	}
	cfg.Mode = Mode(mode)
	cfg.Scenario = Scenario(scenario)
	for _, server := range strings.Split(servers, ",") {
		server = strings.TrimSpace(server)
		if server != "" {
			cfg.NATSServers = append(cfg.NATSServers, server)
		}
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c Config) Validate() error {
	if c.Edges < 1 {
		return fmt.Errorf("edges must be at least 1")
	}
	if c.StartIndex < 1 {
		return fmt.Errorf("start-index must be at least 1")
	}
	if strings.TrimSpace(c.Prefix) == "" {
		return fmt.Errorf("prefix must not be empty")
	}
	if len(c.NATSServers) == 0 {
		return fmt.Errorf("at least one NATS server is required")
	}
	if c.Mode != ModeFullFidelity && c.Mode != ModeMultiplexed {
		return fmt.Errorf("unsupported mode %q", c.Mode)
	}
	if c.Mode == ModeMultiplexed && c.Connections < 1 {
		return fmt.Errorf("connections must be at least 1 in multiplexed mode")
	}
	switch c.Scenario {
	case ScenarioConnections, ScenarioConsumers, ScenarioHeartbeat, ScenarioTelemetry, ScenarioSoak:
	default:
		return fmt.Errorf("unsupported scenario %q", c.Scenario)
	}
	if c.Mode == ModeMultiplexed && (c.Scenario == ScenarioConsumers || c.Scenario == ScenarioSoak) {
		return fmt.Errorf("scenario %q requires full-fidelity mode", c.Scenario)
	}
	if c.HeartbeatInterval <= 0 || c.PositionInterval <= 0 || c.HealthInterval <= 0 {
		return fmt.Errorf("telemetry intervals must be positive")
	}
	if c.Duration < 0 || c.RampDuration < 0 || c.ConnectTimeout <= 0 {
		return fmt.Errorf("durations must not be negative and connect-timeout must be positive")
	}
	if c.SetupConcurrency < 1 {
		return fmt.Errorf("setup-concurrency must be at least 1")
	}
	if c.QueueFetchWait <= 0 {
		return fmt.Errorf("queue-fetch-wait must be positive")
	}
	if c.CommandInterval < 0 {
		return fmt.Errorf("command-interval must not be negative")
	}
	if c.CommandInterval > 0 && c.Scenario != ScenarioConsumers && c.Scenario != ScenarioSoak {
		return fmt.Errorf("command-interval requires consumers or soak scenario")
	}
	return nil
}

func RedactedServers(servers []string) []string {
	redacted := make([]string, len(servers))
	for i, raw := range servers {
		u, err := url.Parse(raw)
		if err != nil || u.User == nil {
			redacted[i] = raw
			continue
		}
		u.User = url.User("REDACTED")
		redacted[i] = u.String()
	}
	return redacted
}
